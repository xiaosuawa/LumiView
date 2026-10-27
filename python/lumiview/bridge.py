from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Sequence

from lumiview.events import WindowEvent
from lumiview.scope import (
    InitContext,
    Plugin,
    Scope,
    ScopePermission,
    check_chain,
    iter_tree,
)
from lumiview.task import run_async
from lumiview.utils import fmt_ms

if TYPE_CHECKING:
    from lumiview.window import Window

log = logging.getLogger("lumiview.bridge")

# BridgeError


class BridgeError(Exception):
    """Structured error returned to JavaScript on bridge call failure.

    Parameters:
        code: Machine-readable error code (e.g. ``"invalid_argument"``).
        message: Human-readable description.
        data: Optional additional context (must be JSON-serializable).
    """

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data

    def to_dict(self) -> dict:
        result: dict = {"code": self.code, "message": str(self)}
        if self.data is not None:
            result["data"] = self.data
        return result


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
        """Get or create a child scope (forwarded to the root
        :class:`Scope`)."""

        return self._root.scope(name)

    def command(
        self,
        fn: Callable | None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable:
        """Register a command on the root scope (decorator or direct
        call) — see :meth:`Scope.command`."""

        return self._root.command(fn, name=name, replace=replace, strict=strict)

    def include(self, other: Scope) -> None:
        """Mount a scope onto the tree (pure mounting, see
        :meth:`Scope.include`).

        An instance can only be mounted once. Custom mount names are set
        at construction (``Scope(name=...)``). Instances always end up
        on the tree, so their lifecycle hooks (:class:`Plugin`) are
        reachable via tree walk — no extra hook list needed.
        """
        self._root.include(other)

    def allow(self, *patterns: str) -> None:
        """Append allow rules on the root scope (see
        :meth:`Scope.allow`)."""

        self._root.allow(*patterns)

    def deny(self, *patterns: str) -> None:
        """Append deny rules on the root scope (see :meth:`Scope.deny`)."""

        self._root.deny(*patterns)

    # Plugin lifecycle (driven by Window.create)

    def _run_on_init(self, ctx: InitContext) -> InitContext:
        """Run every Plugin's on_init hook in tree order (root → leaves)."""
        for scope in iter_tree(self._root):
            if isinstance(scope, Plugin):
                ctx = scope.on_init(ctx) or ctx
        return ctx

    def _run_on_ready(self, window: "Window") -> None:
        """Run every Plugin's on_ready hook (once per window using this bridge)."""
        for scope in iter_tree(self._root):
            if isinstance(scope, Plugin):
                scope.on_ready(window)

    # IPC dispatch

    def _on_message(self, window: "Window", raw: str, *, send: Callable[[str], None] | None = None) -> None:
        """Called from the main thread by wryview's IPC handler.

        *window* is passed by the Window's own IPC handler (which closes
        over ``self``) — no webview → Window mapping needed. The unsendable
        WebView is never captured into the asyncio coroutine below; it is
        only touched on the main thread (inside ``_respond``'s callback).

        *send* is a test-only injection forwarded to :meth:`_respond` so a
        synchronous branch (e.g. an unknown command) can be asserted without
        a live app/WebView. Defaults to ``None`` — no behaviour change.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            log.debug(f"Ignoring non-object bridge message: {raw[:200]!r}")
            return

        msg_type = data.get("type", "")
        if msg_type == "emit":
            event_name = data.get("event")
            if not isinstance(event_name, str) or not event_name:
                log.debug(f"Ignoring emit without a valid event name: {raw[:200]!r}")
                return
            # Fire-and-forget notification — not a command, so it does
            # not go through the scope permission chain. `untrusted`
            # windows never reach this method (no bridge script).
            window._emit(
                WindowEvent.JsEvent(
                    event=event_name,
                    payload=data.get("payload"),
                )
            )
            return
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
                send=send,
            )
            return

        if not check_chain(cmd.scope, command):
            self._respond(
                window,
                call_id,
                error=BridgeError("forbidden", f"Command {command!r} is not allowed"),
                send=send,
            )
            return

        # Schedule on the asyncio loop (never the GUI thread)
        from lumiview.app import App

        try:
            app = App.get()
        except RuntimeError:
            self._respond(
                window,
                call_id,
                error=BridgeError("internal_error", "App not running"),
                send=send,
            )
            return

        loop = app._async_loop
        if loop is None:
            self._respond(
                window,
                call_id,
                error=BridgeError("internal_error", "App not running"),
                send=send,
            )
            return

        async def _run_async_cmd() -> None:
            t0 = time.monotonic()
            log.debug("IPC invoke %s (id=%s) start", cmd.full_name, call_id)
            try:
                from lumiview._binding import bind_arguments  # avoid import cycle

                kwargs = bind_arguments(cmd, payload, window)
                result = await run_async(cmd.fn, **kwargs)
                log.debug(
                    "IPC invoke %s (id=%s) ok in %.1fms",
                    cmd.full_name, call_id, fmt_ms(t0),
                )
                self._respond(window, call_id, result=result)
            except BridgeError as e:
                log.debug(
                    "IPC invoke %s (id=%s) rejected in %.1fms: %s",
                    cmd.full_name, call_id, fmt_ms(t0), e,
                )
                self._respond(window, call_id, error=e)
            except Exception as e:
                log.exception(
                    "Bridge command %r failed in %.1fms", cmd.full_name, fmt_ms(t0)
                )
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
        send: Callable[[str], None] | None = None,
    ) -> None:
        """Send a response back to JavaScript via eval_js on the main thread.

        The WebView is read from *window* inside the main-thread callback
        so the unsendable object is only ever referenced on the main
        thread.

        *send* is a test-only injection: when provided, it receives the
        ready ``window.lumiview._dispatchResponse(...)`` script instead of
        dispatching it through the app on the main thread (which needs a
        live :class:`~lumiview.app.App` and a real WebView). Defaults to
        ``None``, preserving the production path unchanged.
        """
        from lumiview.app import App

        if error is not None:
            payload = json.dumps(
                {"type": "reject", "id": call_id, "error": error.to_dict()}
            )
        else:
            payload = json.dumps({"type": "resolve", "id": call_id, "value": result})

        script = f"window.lumiview._dispatchResponse({payload})"

        if send is not None:
            send(script)
            return

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

  // Dedicated EventTarget — its listener registry lives outside the DOM
  // event namespace, so `emit("click")` cannot trigger real click
  // handlers and no type prefix is needed.
  const lv = new EventTarget();
  lv._nextId = 0;

  /** Call a Python command. Returns a Promise. */
  lv.invoke = function (command, payload = {}) {
    return new Promise((resolve, reject) => {
      const id = String(++lv._nextId);
      _pending[id] = { resolve, reject };
      window.ipc.postMessage(JSON.stringify({
        type: "invoke",
        id: id,
        command: command,
        payload: payload,
      }));
    });
  };

  /**
   * Send a fire-and-forget event to Python.
   *
   * Received as `WindowEvent.JsEvent`; filter it with `where=`:
   *
   *     win.on(WindowEvent.JsEvent, where=when(event="data.changed"))(fn)
   *
   * Use `invoke()` instead when you need a return value.
   */
  lv.emit = function (event, payload = null) {
    window.ipc.postMessage(JSON.stringify({
      type: "emit",
      event: event,
      payload: payload,
    }));
  };

  /**
   * Listen for an event sent from Python via `win.emit()`.
   *
   * Sugar over `window.lumiview.addEventListener(event, (e) => e.detail)`.
   * Returns an unsubscribe function::
   *
   *     const unlisten = window.lumiview.listen("scheduler.updated", (p) => {
   *         console.log(p);
   *     });
   *     unlisten();
   */
  lv.listen = function (event, handler, options) {
    const wrapped = (e) => {
      try { handler(e.detail); } catch (err) { console.error(err); }
    };
    // removeEventListener only matches on `capture`.
    const capture = !!(options && typeof options === "object"
      ? options.capture
      : options);
    lv.addEventListener(event, wrapped, options);
    return () => lv.removeEventListener(event, wrapped, capture);
  };

  // ── Direct dispatch (called by Python via eval_js) ──────────────────

  /** Resolve or reject a pending invoke() Promise. */
  lv._dispatchResponse = function (detail) {
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
  };

  /** Dispatch a Python-emitted event on this EventTarget. */
  lv._dispatchEvent = function (detail) {
    lv.dispatchEvent(new CustomEvent(detail.event, {
      detail: detail.payload,
    }));
  };

  window.lumiview = lv;
})();
"""
