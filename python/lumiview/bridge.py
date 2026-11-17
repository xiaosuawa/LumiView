from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Sequence, TypeVar, overload

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
from lumiview._utils import fmt_ms

if TYPE_CHECKING:
    from lumiview.window import Window

_log = logging.getLogger("lumiview.bridge")

_F = TypeVar("_F", bound=Callable[..., Any])

class BridgeError(Exception):
    """Structured error returned to JavaScript (``code``, ``message``, ``data``)."""

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.data is not None:
            result["data"] = self.data
        return result


class Bridge:
    """Registry of Python functions callable from JavaScript.

    Composes an anonymous root :class:`Scope`; ``bridge=None`` disables the bridge.
    """

    def __init__(
        self,
        *,
        includes: Sequence[Scope] = (),
        permissions: ScopePermission | None = None,
    ) -> None:
        self._root = Scope(
            permissions=permissions or ScopePermission(allow=("*",)), includes=includes
        )

    def scope(self, name: str) -> Scope:
        """Get or create a child scope (forwarded to the root
        :class:`Scope`)."""

        return self._root.scope(name)

    @overload
    def command(
        self,
        fn: _F,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> _F: ...

    @overload
    def command(
        self,
        fn: None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable[[_F], _F]: ...

    def command(
        self,
        fn: Callable[..., Any] | None = None,
        /,
        *,
        name: str | None = None,
        replace: bool = False,
        strict: bool = True,
    ) -> Callable[..., Any]:
        """Register a command on the root scope (decorator or direct
        call) — see :meth:`Scope.command`."""

        if fn is None:
            return self._root.command(name=name, replace=replace, strict=strict)
        return self._root.command(fn, name=name, replace=replace, strict=strict)

    def include(self, other: Scope) -> None:
        """Mount a scope onto the tree (once; names are set at construction)."""
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

    def _on_message(
        self, window: "Window", raw: str, *, send: Callable[[str], None] | None = None
    ) -> None:
        """wryview IPC handler (main thread).

        *window* comes from the Window's own handler; *send* is a test-only injection.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            _log.debug(f"Ignoring non-object bridge message: {raw[:200]!r}")
            return

        msg_type = data.get("type", "")
        if msg_type == "emit":
            event_name = data.get("event")
            if not isinstance(event_name, str) or not event_name:
                _log.debug(f"Ignoring emit without a valid event name: {raw[:200]!r}")
                return
            # Not a command: no permission chain. `untrusted` never gets here.
            window._emit(
                WindowEvent.JsEvent(
                    event=event_name,
                    payload=data.get("payload"),
                )
            )
            return
        if msg_type != "invoke":
            _log.warning(f"Unknown bridge message type: {msg_type!r}")
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
            _log.debug("IPC invoke %s (id=%s) start", cmd.full_name, call_id)
            try:
                from lumiview._binding import bind_arguments  # avoid import cycle

                kwargs = bind_arguments(cmd, payload, window)
                result = await run_async(cmd.fn, **kwargs)
                _log.debug(
                    "IPC invoke %s (id=%s) ok in %.1fms",
                    cmd.full_name,
                    call_id,
                    fmt_ms(t0),
                )
                self._respond(window, call_id, result=result)
            except BridgeError as e:
                _log.debug(
                    "IPC invoke %s (id=%s) rejected in %.1fms: %s",
                    cmd.full_name,
                    call_id,
                    fmt_ms(t0),
                    e,
                )
                self._respond(window, call_id, error=e)
            except Exception as e:
                _log.exception(
                    "Bridge command %r failed in %.1fms", cmd.full_name, fmt_ms(t0)
                )
                self._respond(
                    window,
                    call_id,
                    error=BridgeError("internal_error", str(e)),
                )

        if not app._spawn(_run_async_cmd()):
            # No loop: answer the page instead of leaving invoke() pending.
            self._respond(
                window,
                call_id,
                error=BridgeError("internal_error", "App is shutting down"),
                send=send,
            )

    @staticmethod
    def _respond(
        window: "Window",
        call_id: str,
        *,
        result: Any = None,
        error: BridgeError | None = None,
        send: Callable[[str], None] | None = None,
    ) -> None:
        """Deliver a response via ``eval_js`` on the main thread.

        *send* is a test-only injection (receives the dispatch script instead).
        """
        from lumiview.app import App

        if error is not None:
            message = {"type": "reject", "id": call_id, "error": error.to_dict()}
        else:
            message = {"type": "resolve", "id": call_id, "value": result}

        script = dispatch_script(message)

        if send is not None:
            send(script)
            return

        def _send() -> None:
            webview = window._webview  # main thread — safe to touch and drop
            if webview is None:
                _log.warning("Bridge response dropped: WebView is closed")
                return
            try:
                webview.eval_js(script)
            except Exception:
                _log.exception("Failed to send bridge response")

        app = App.get()
        app.call_on_main(_send)


_CLIENT_SCRIPT_HINT = (
    "LumiView's JS client is not built — run:\n"
    "    npm --prefix js install\n"
    "    npm --prefix js run build"
)


def client_script() -> str:
    """Return the injected JS client source (built from ``js/src``)."""
    try:
        from lumiview._bridge_client import CLIENT_SCRIPT
    except ImportError as exc:  # pragma: no cover - build-time guard
        raise RuntimeError(_CLIENT_SCRIPT_HINT) from exc
    return CLIENT_SCRIPT


def dispatch_script(message: dict[str, Any], *, default: Any = None) -> str:
    """Return the ``eval_js`` call that delivers *message* to the page client."""
    return f"window.__LUMIVIEW__.dispatch({json.dumps(message, default=default)})"
