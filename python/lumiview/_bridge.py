from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Sequence

from lumiview._scope import (
    BridgeError,
    InitContext,
    Scope,
    ScopePermission,
    check_chain,
    iter_tree,
)
from lumiview._task import _run_async

if TYPE_CHECKING:
    from lumiview._window import Window

log = logging.getLogger("lumiview.bridge")

# Bridge

class Bridge:
    """Registry of Python functions callable from JavaScript.

    Composes an anonymous root :class:`Scope`; tree operations are
    forwarded to it. ``bridge=None`` disables the bridge entirely for
    a window.

    Convenience constructor arguments (equivalent to calling the methods
    after creation)::

        bridge = Bridge(
            includes=[WindowControls()],
            permissions=ScopePermission(allow=("fs.*",)),
        )
    """

    def __init__(
        self,
        *,
        includes: Sequence[Scope] = (),
        permissions: ScopePermission | None = None,
    ) -> None:
        self._root = Scope(
            permissions=permissions or ScopePermission(allow=("*",)),
            includes=includes
        )

    # Tree facade

    def scope(self, name: str) -> Scope:
        return self._root.scope(name)

    def command(
        self,
        fn: Callable[..., Any] | None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable[..., Any]:
        return self._root.command(fn, name=name, replace=replace, strict=strict)

    def include(self, other: Scope) -> None:
        """Mount a scope onto the tree (pure mounting, see Scope.include).

        An instance can only be mounted once. Custom mount names are set
        at construction (``Scope(name=...)``). Instances always end up
        on the tree, so their on_init/on_ready hooks are reachable via
        tree walk — no extra hook list needed.
        """
        self._root.include(other)

    def allow(self, *patterns: str) -> None:
        self._root.allow(*patterns)

    def deny(self, *patterns: str) -> None:
        self._root.deny(*patterns)

    # Plugin lifecycle (driven by Window.create)

    def _run_on_init(self, ctx: InitContext) -> InitContext:
        """Run every on_init hook in tree order (root → leaves)."""
        for scope in iter_tree(self._root):
            on_init = getattr(scope, "on_init", None)
            if on_init is not None:
                ctx = on_init(ctx) or ctx
        return ctx

    def _run_on_ready(self, window: "Window") -> None:
        """Run every on_ready hook (once per window using this bridge)."""
        for scope in iter_tree(self._root):
            on_ready = getattr(scope, "on_ready", None)
            if on_ready is not None:
                on_ready(window)

    # IPC dispatch

    def _on_message(self, window: "Window", raw: str) -> None:
        """Called from the main thread by wryview's IPC handler.

        *window* is passed by the Window's own IPC handler (which closes
        over ``self``) — no webview → Window mapping needed. The unsendable
        WebView is never captured into the asyncio coroutine below; it is
        only touched on the main thread (inside ``_respond``'s callback).
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            log.debug(f"Ignoring non-object bridge message: {raw[:200]!r}")
            return

        msg_type = data.get("type", "")
        if msg_type != "invoke":
            log.warning(f"Unknown bridge message type: {msg_type!r}")
            return

        command = data.get("command", "")
        call_id = data.get("id", "")
        payload = data.get("payload", {})

        if not call_id or not command:
            return

        cmd = self._root.lookup(command)
        if cmd is None:
            self._respond(
                window,
                call_id,
                error=BridgeError("unknown_command", f"Unknown command: {command}"),
            )
            return

        if not check_chain(cmd.scope, command):
            self._respond(
                window,
                call_id,
                error=BridgeError("forbidden", f"Command {command!r} is not allowed"),
            )
            return

        # Schedule on the asyncio loop (never the GUI thread)
        from lumiview._app import App

        try:
            app = App.get()
        except RuntimeError:
            self._respond(
                window,
                call_id,
                error=BridgeError("internal_error", "App not running"),
            )
            return

        loop = app._async_loop
        if loop is None:
            self._respond(
                window,
                call_id,
                error=BridgeError("internal_error", "App not running"),
            )
            return

        async def _run_async_cmd() -> None:
            try:
                from lumiview._binding import bind_arguments  # avoid import cycle

                kwargs = bind_arguments(cmd, payload, window)
                result = await _run_async(cmd.fn, pool=app._threadpool, **kwargs)
                self._respond(window, call_id, result=result)
            except BridgeError as e:
                self._respond(window, call_id, error=e)
            except Exception as e:
                log.exception(f"Bridge command {cmd.full_name!r} failed")
                self._respond(
                    window,
                    call_id,
                    error=BridgeError("internal_error", str(e)),
                )

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_run_async_cmd()))

    # Response

    @staticmethod
    def _respond(
        window: "Window",
        call_id: str,
        *,
        result: Any = None,
        error: BridgeError | None = None,
    ) -> None:
        """Send a response back to JavaScript via eval_js on the main thread.

        The WebView is read from *window* inside the main-thread callback
        so the unsendable object is only ever referenced on the main
        thread.
        """
        from lumiview._app import App

        if error is not None:
            payload = json.dumps(
                {"type": "reject", "id": call_id, "error": error.to_dict()}
            )
        else:
            payload = json.dumps({"type": "resolve", "id": call_id, "value": result})

        script = f"window.lumiview._dispatchResponse({payload})"

        def _send() -> None:
            webview = window._webview  # main thread — safe to touch and drop
            if webview is None:
                log.warning("Bridge response dropped: WebView is closed")
                return
            try:
                webview.eval_js(script)
            except Exception:
                log.exception("Failed to send bridge response")

        app = App.get()
        app.call_on_main(_send)


# Injected JavaScript

BRIDGE_SCRIPT = """\
(() => {
  if (window.lumiview && window.lumiview.invoke) return;

  const _pending = {};
  const _listeners = {};

  window.lumiview = {
    _nextId: 0,

    /** Call a Python command. Returns a Promise. */
    invoke(command, payload = {}) {
      return new Promise((resolve, reject) => {
        const id = String(++window.lumiview._nextId);
        _pending[id] = { resolve, reject };
        window.ipc.postMessage(JSON.stringify({
          type: "invoke",
          id: id,
          command: command,
          payload: payload,
        }));
      });
    },

    /**
     * Listen for events sent from Python via ``window.emit()``.
     *
     * Returns an unsubscribe function::
     *
     *     const unlisten = window.lumiview.listen("scheduler.updated", (payload) => {
     *         console.log(payload);
     *     });
     *
     *     // Later:
     *     unlisten();
     */
    listen(event, handler) {
      if (!_listeners[event]) {
        _listeners[event] = [];
      }
      _listeners[event].push(handler);
      return () => {
        const handlers = _listeners[event];
        if (handlers) {
          const idx = handlers.indexOf(handler);
          if (idx >= 0) handlers.splice(idx, 1);
        }
      };
    },

    // ── Direct dispatch (called by Python via eval_js) ──────────────────

    /** Resolve or reject a pending invoke() Promise. */
    _dispatchResponse(detail) {
      const p = _pending[detail.id];
      if (!p) return;
      delete _pending[detail.id];

      if (detail.type === "reject") {
        const err = detail.error || {};
        const e = new Error(err.message || "Bridge error");
        e.code = err.code || "internal_error";
        e.data = err.data;
        p.reject(e);
      } else {
        p.resolve(detail.value);
      }
    },

    /** Dispatch a Python-emitted event to JS listeners. */
    _dispatchEvent(detail) {
      const handlers = _listeners[detail.event] || [];
      for (const h of handlers) {
        try { h(detail.payload); } catch (e) { console.error(e); }
      }
    },
  };
})();
"""
