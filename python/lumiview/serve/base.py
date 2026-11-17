"""Request/response types and the handler base for ``lumiview://`` handlers.

A :class:`Serve` must call ``respond(status, headers, body)`` exactly once.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from lumiview.task import run_async

# Called exactly once, from any thread.
RespondFn = Callable[[int, list[tuple[str, str]], bytes], None]

_log = logging.getLogger("lumiview.serve.base")

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*$")


def _check_scheme(scheme: str) -> str:
    """Validate a custom protocol scheme name (RFC 3986) and return it."""
    if not isinstance(scheme, str) or not _SCHEME_RE.match(scheme or ""):
        raise ValueError(
            f"Invalid custom protocol scheme: {scheme!r} "
            "(must start with a letter and contain only "
            "letters, digits, '+', '-', '.')"
        )
    return scheme


@dataclass(frozen=True)
class Request:
    """Incoming request from the WebView custom protocol handler."""

    method: str
    url: str
    path: str
    query: str
    headers: list[tuple[str, str]]
    body: bytes


@dataclass
class Response:
    """Response to send back to the WebView."""

    status: int = 200
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""


class Serve:
    """Base class for custom scheme handlers (sync; runs on the protocol thread)."""

    def __init__(self, *, scheme: str = "lumiview") -> None:
        self.scheme = _check_scheme(scheme)

    def __call__(self, request: Request, respond: RespondFn) -> None:
        raise NotImplementedError(
            f"{type(self).__name__} must implement __call__(request, respond)"
        )


class Handler(Serve):
    """Adapt a plain function returning a :class:`Response` into a :class:`Serve`.

    Sync functions run on the App's thread pool, async ones on its loop.
    """

    def __init__(
        self,
        fn: Callable[[Request], Response | Awaitable[Response]],
        *,
        scheme: str = "lumiview",
    ) -> None:
        super().__init__(scheme=scheme)
        self._fn = fn

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Handle one request; ``respond()`` runs on the asyncio thread."""
        from lumiview.app import App, AppState

        app = App.get()
        loop = app._async_loop
        if loop is None:
            respond(503, [("Content-Type", "text/plain")], b"App is shutting down")
            return

        responded = False

        def _once(status: int, headers: list[tuple[str, str]], body: bytes) -> None:
            """Deliver the response exactly once — later calls are dropped."""
            nonlocal responded
            if responded:
                _log.warning(
                    "Serve responder called twice (status=%s) — dropping", status
                )
                return
            responded = True
            respond(status, headers, body)

        async def _run() -> None:
            try:
                result = await run_async(self._fn, request)
            except asyncio.CancelledError:
                # The window may already be gone — do not answer, just unwind.
                _log.debug("serve handler cancelled during shutdown")
                raise
            except BaseException:
                _log.exception("Serve handler raised an exception")
                if app.is_running:
                    _once(
                        500,
                        [("Content-Type", "text/plain")],
                        b"Internal Server Error",
                    )
                return
            _once(result.status, result.headers, result.body)

        if not app._spawn(_run()):
            # The loop closed between the check and the dispatch — answer 503.
            _log.warning("asyncio loop closed while dispatching a serve request")
            _once(503, [("Content-Type", "text/plain")], b"App is shutting down")
