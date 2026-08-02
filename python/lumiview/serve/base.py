"""
Serve — request / response types and the handler base class for
custom scheme handlers.

A :class:`Serve` receives a :class:`Request` and a ``respond`` callback.
It must call ``respond(status, headers, body)`` exactly once to deliver the
response. The handler may do so synchronously or from any thread / event loop
— the framework never blocks waiting for it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from lumiview._task import _run_async

RespondFn = Callable[[int, list[tuple[str, str]], bytes], None]

log = logging.getLogger("lumiview.serve.base")

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
    """Incoming request from the WebView custom protocol handler.

    Attributes:
        method: HTTP method (``"GET"``, ``"HEAD"``, etc.).
        url: Full ``lumiview://app/...`` URL.
        path: Path component (``"/"``, ``"/index.html"``, etc.).
        query: Query string without ``?`` (``""`` if none).
        headers: Request headers as ``list[tuple[str, str]]``.
            Duplicate keys are allowed (e.g. multiple ``Accept``).
        body: Raw request body bytes.
    """

    method: str
    url: str
    path: str
    query: str
    headers: list[tuple[str, str]]
    body: bytes


@dataclass
class Response:
    """Response to send back to the WebView.

    Attributes:
        status: HTTP status code (default ``200``).
        headers: Response headers as ``list[tuple[str, str]]``.
            Duplicate keys are allowed (e.g. multiple ``Set-Cookie``).
        body: Response body bytes.
    """

    status: int = 200
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""


# Serve base class


class Serve:
    """Base class for custom scheme handlers.

    A ``Serve`` receives a :class:`Request` and a ``respond`` callback.
    It must call ``respond(status, headers, body)`` exactly once — the
    framework does **not** inspect the return value::

        class MyHandler(Serve):
            def __call__(self, request: Request, respond: RespondFn) -> None:
                respond(200, [], b"hello")

    The ``scheme`` parameter names the custom protocol this handler is
    registered under (default ``"lumiview"``). To serve a plain function
    that returns a :class:`Response`, use :class:`Handler`.
    """

    def __init__(self, *, scheme: str = "lumiview") -> None:
        self.scheme = _check_scheme(scheme)

    def __call__(self, request: Request, respond: RespondFn) -> None:
        raise NotImplementedError(
            f"{type(self).__name__} must implement __call__(request, respond)"
        )


# Convenience: Handler from a plain function


class Handler(Serve):
    """Adapt a plain function into a :class:`Serve` handler.

    The function receives a :class:`Request` and must return a
    :class:`Response`. Sync functions run on the App's thread pool;
    async functions run on the App's asyncio loop — both via the same
    ``_run_async`` dispatch used for bridge commands and hook handlers::

        def my_handler(request: Request) -> Response:
            return Response(200, body=b"OK")

        async def my_async_handler(request: Request) -> Response:
            await something()
            return Response(200, body=b"OK")

        win = await Window.create(source=Handler(my_handler))

    Parameters:
        fn: Handler function.
        scheme: Name of the custom protocol this handler is registered
            under (default ``"lumiview"``).

    Usage::

        win = await Window.create(source=Handler(my_api, scheme="api"))
    """

    def __init__(
        self,
        fn: Callable[[Request], Response],
        *,
        scheme: str = "lumiview",
    ) -> None:
        super().__init__(scheme=scheme)
        self._fn = fn

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Handle one request — dispatched to the App's asyncio loop.

        Returns immediately; ``respond()`` is called from the asyncio
        thread when the handler finishes (or fails).
        """
        from lumiview._app import App

        app = App.get()
        loop = app._async_loop
        if loop is None:
            respond(500, [("Content-Type", "text/plain")], b"App not running")
            return

        async def _run() -> None:
            try:
                result = await _run_async(self._fn, request, pool=app._threadpool)
                respond(result.status, result.headers, result.body)
            except Exception:
                log.exception("Serve handler raised an exception")
                respond(500, [("Content-Type", "text/plain")], b"Internal Server Error")

        asyncio.run_coroutine_threadsafe(_run(), loop)
