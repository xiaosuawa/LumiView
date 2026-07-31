from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from wryview import WebView

from lumiview._task import _run_async

log = logging.getLogger("lumiview.bridge")


# ═══════════════════════════════════════════════════════════════════════════
# BridgeError — structured errors
# ═══════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════
# Permission model
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BridgePermission:
    """Permission rules for a Bridge instance.

    Default: all commands allowed, 1 MB request limit, 64 concurrent per page.
    """

    allowed_commands: list[str] = field(default_factory=lambda: ["*"])
    max_request_size: int = 1024 * 1024  # 1 MB
    max_concurrent_per_page: int = 64

    def check_command(self, command: str) -> bool:
        """Check if a command is allowed.

        Patterns use ``:`` as capability separator (Tauri convention):

        - ``"*"`` — allow all commands
        - ``"storage:*"`` — allow all ``storage.*`` commands
        - ``"settings:read"`` — allow exact command
        """
        for pattern in self.allowed_commands:
            if pattern == "*":
                return True
            # Normalize : to . for command name comparison
            normalized = pattern.replace(":", ".")
            if normalized.endswith("*"):
                prefix = normalized[:-1]
                if command.startswith(prefix):
                    return True
            elif command == normalized:
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Bridge
# ═══════════════════════════════════════════════════════════════════════════


class Bridge:
    """Registry of Python functions callable from JavaScript.

    Each window can have its own Bridge, or multiple windows can share one.
    Set ``bridge=None`` to disable bridge entirely for a window.
    """

    def __init__(
        self,
        permission: BridgePermission | None = None,
    ) -> None:
        self._funcs: dict[str, Callable[..., Any]] = {}
        self._permission = permission or BridgePermission()
        self._concurrent_count = 0
        self._concurrent_lock = threading.Lock()

    # ── Registration ────────────────────────────────────────────────────

    def command(
        self,
        name_or_fn: str | Callable[..., Any] | None = None,
        /,
        *,
        replace: bool = False,
    ):
        """Decorator to register a bridge command.

        Can be used as ``@bridge.command`` (uses function name) or
        ``@bridge.command("storage.save_all")`` (explicit name).

        Sync commands run on the thread pool; async commands run on the
        asyncio loop.  Neither runs on the GUI thread.
        """
        if callable(name_or_fn):
            return self._register(name_or_fn.__name__, name_or_fn, replace)

        # name_or_fn is str (or None → fallback to fn.__name__ inside decorator)
        _name = name_or_fn if isinstance(name_or_fn, str) else ""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._register(_name or fn.__name__, fn, replace)
            return fn

        return decorator

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a function by name (non-decorator style)."""
        self._register(name, fn, replace=True)

    def _register(
        self, name: str, fn: Callable[..., Any], replace: bool
    ) -> Callable[..., Any]:
        if name in self._funcs and not replace:
            raise ValueError(
                f"Command {name!r} already registered. "
                "Use replace=True to overwrite."
            )
        self._funcs[name] = fn
        return fn

    # ── Permission ──────────────────────────────────────────────────────

    def allow(
        self,
        *,
        commands: list[str] | None = None,
    ) -> None:
        """Set allowed commands.

        Commands use capability-style patterns:

        - ``"storage:*"`` — all storage.* commands
        - ``"*"`` — everything
        """
        if commands is not None:
            self._permission.allowed_commands = list(commands)

    # ── IPC dispatch ────────────────────────────────────────────────────

    def _on_message(self, wv: WebView, raw: str) -> None:
        """Called from the main thread by wryview's IPC handler."""
        
        # Check request size
        if len(raw) > self._permission.max_request_size:
            log.warning("IPC message exceeds max request size, droped.")
            return
        
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type", "")
        if msg_type != "invoke":
            log.warning("Unknown bridge message type: %r", msg_type)
            return

        command = data.get("command", "")
        call_id = data.get("id", "")
        payload = data.get("payload", {})

        if not call_id or not command:
            return

        # Check command permission
        if not self._permission.check_command(command):
            self._respond(
                wv,
                call_id,
                error=BridgeError("forbidden", f"Command {command!r} is not allowed"),
            )
            return

        # Check concurrency
        with self._concurrent_lock:
            if self._concurrent_count >= self._permission.max_concurrent_per_page:
                self._respond(
                    wv,
                    call_id,
                    error=BridgeError(
                        "too_many_requests", "Too many concurrent requests"
                    ),
                )
                return
            self._concurrent_count += 1

        entry = self._funcs.get(command)
        if entry is None:
            with self._concurrent_lock:
                self._concurrent_count -= 1
            self._respond(
                wv,
                call_id,
                error=BridgeError("unknown_command", f"Unknown command: {command}"),
            )
            return

        self._dispatch(wv, call_id, command, entry, payload)

    def _dispatch(
        self,
        wv: WebView,
        call_id: str,
        command: str,
        fn: Callable[..., Any],
        payload: Any,
    ) -> None:
        """Dispatch to asyncio loop or thread pool — NEVER the GUI thread."""
        from lumiview._app import App

        try:
            app = App.get()
        except RuntimeError:
            self._respond(
                wv, call_id, error=BridgeError("internal_error", "App not running")
            )
            return

        loop = app._async_loop
        if loop is None:
            self._respond(
                wv, call_id, error=BridgeError("internal_error", "App not running")
            )
            return

        async def _run_async_cmd() -> None:
            try:
                result = await _run_async(
                    fn,
                    payload,
                    pool=app._threadpool,
                )
                self._respond(wv, call_id, result=result)
            except BridgeError as e:
                self._respond(wv, call_id, error=e)
            except Exception as e:
                log.exception("Bridge command %r failed", command)
                self._respond(
                    wv,
                    call_id,
                    error=BridgeError("internal_error", str(e)),
                )
            finally:
                with self._concurrent_lock:
                    self._concurrent_count -= 1

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_run_async_cmd()))

    # ── Response ─────────────────────────────────────────────────────────

    @staticmethod
    def _respond(
        wv: WebView,
        call_id: str,
        *,
        result: Any = None,
        error: BridgeError | None = None,
    ) -> None:
        """Send a response back to JavaScript via eval_js on the main thread."""
        from lumiview._app import App

        if error is not None:
            payload = json.dumps(
                {
                    "type": "reject",
                    "id": call_id,
                    "error": error.to_dict(),
                }
            )
        else:
            payload = json.dumps(
                {
                    "type": "resolve",
                    "id": call_id,
                    "value": result,
                }
            )

        script = f"window.lumiview._dispatchResponse({payload})"

        def _send() -> None:
            try:
                wv.eval_js(script)
            except Exception:
                log.exception("Failed to send bridge response")

        app = App.get()
        app.call_on_main(_send)


# ═══════════════════════════════════════════════════════════════════════════
# Injected JavaScript
# ═══════════════════════════════════════════════════════════════════════════

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
