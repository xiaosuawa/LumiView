"""
ASGI adapter — run an ASGI application inside a ``lumiview://`` custom protocol.

ASGI is the asynchronous successor to WSGI, used by modern Python web
frameworks like FastAPI, Starlette, and Quart.

.. warning::

    **Do not use streaming responses.**  ``StreamingResponse``, SSE,
    chunked transfer encoding, WebSocket — none of these work through
    the ``lumiview://`` custom protocol.  The protocol calls
    ``respond()`` exactly once with the complete body.  A streaming
    endpoint will appear to hang and may block the UI until timeout.

Limitations (inherent to the custom protocol, not ASGI-specific):

- No WebSocket support.
- No streaming / SSE — the full response body is buffered.
- Request body is fully buffered (delivered as a single chunk).
- Lifespan events are not emitted.

Usage::

    from fastapi import FastAPI
    fastapi_app = FastAPI()

    win = await Window.create(source=ASGI(fastapi_app))
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import unquote, urlparse

from lumiview.serve.base import Request, RespondFn, _check_scheme

log = logging.getLogger("lumiview.serve.asgi")


class ASGI:
    """Adapt an ASGI application to the :class:`~lumiview.serve.Serve` protocol.

    Each request is dispatched to the App's asyncio event loop via
    ``asyncio.run_coroutine_threadsafe`` — the caller returns immediately
    and the response is delivered when the ASGI app finishes.

    Parameters:
        app: An ASGI application callable ``(scope, receive, send)``.
        max_body: Maximum response body size in bytes (default 10 MiB).
            Responses exceeding this limit return a 500 error.
        timeout: Seconds to wait for the ASGI app to produce a response
            (default 30).  A 504 Gateway Timeout is returned on expiry.
        scheme: Name of the custom protocol this app is served under
            (default ``"lumiview"``).

    .. note::

        This adapter requires no external dependencies — it implements
        the ASGI 3.0 protocol directly on top of ``asyncio``.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_body: int = 10 * 1024 * 1024,
        timeout: float = 30,
        scheme: str = "lumiview",
    ) -> None:
        self._app = app
        self._max_body = max_body
        self._timeout = timeout
        self.scheme = _check_scheme(scheme)

    # ── Serve protocol ─────────────────────────────────────────────────

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Handle one request — dispatches to the App's asyncio loop.

        Returns immediately; ``respond()`` is called from the asyncio
        thread when the ASGI app finishes (or times out).  ``respond``
        is guaranteed to be invoked at most once — a duplicate call
        (e.g. an app that raises after sending its final body) is dropped.
        """
        from lumiview._app import App

        loop = App.get()._async_loop
        if loop is None:
            respond(500, [("Content-Type", "text/plain")], b"App not running")
            return

        responded = False

        def _once(status: int, headers: list[tuple[str, str]], body: bytes) -> None:
            """Deliver the response exactly once — later calls are dropped."""
            nonlocal responded
            if responded:
                log.warning(
                    f"ASGI responder called a second time (status={status}) — "
                    "dropping duplicate response",
                )
                return
            responded = True
            respond(status, headers, body)

        async def _run() -> None:
            try:
                await asyncio.wait_for(
                    self._execute(request, _once), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                log.error(f"ASGI app did not complete within {self._timeout:.1f}s")
                _once(504, [("Content-Type", "text/plain")], b"Gateway Timeout")
            except BaseException:
                log.exception("ASGI app raised an exception")
                _once(500, [("Content-Type", "text/plain")], b"Internal Server Error")

        asyncio.run_coroutine_threadsafe(_run(), loop)

    # ── ASGI protocol (runs on the asyncio loop) ───────────────────────

    async def _execute(self, request: Request, respond: RespondFn) -> None:
        """Run the ASGI app and deliver the response via ``respond()``."""
        scope = self._build_scope(request)

        status: int = 500
        headers: list[tuple[str, str]] = []
        body_chunks: list[bytes] = []
        finished = False

        # ── ASGI receive callable ──────────────────────────────────────
        async def receive() -> dict[str, Any]:
            return {
                "type": "http.request",
                "body": request.body,
                "more_body": False,
            }

        # ── ASGI send callable ─────────────────────────────────────────
        async def send(message: dict[str, Any]) -> None:
            nonlocal status, headers, finished

            if message["type"] == "http.response.start":
                status = message["status"]
                raw_headers = message.get("headers", [])
                for k, v in raw_headers:
                    key = k.decode("latin-1") if isinstance(k, bytes) else k
                    val = v.decode("latin-1") if isinstance(v, bytes) else v
                    headers.append((key, val))

            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    body_chunks.append(chunk)
                if not message.get("more_body", False):
                    finished = True
                    self._finish(status, headers, body_chunks, respond)

        # ── Invoke ─────────────────────────────────────────────────────
        await self._app(scope, receive, send)

        if not finished:
            # The app returned without sending a final body — the
            # protocol callback would otherwise hang forever.  respond
            # here is the deduped _once wrapper, so a late body from a
            # background task is dropped.
            log.error("ASGI app returned without sending a final http.response.body")
            respond(500, [("Content-Type", "text/plain")], b"Internal Server Error")

    # ── Response assembly ──────────────────────────────────────────────

    def _finish(
        self,
        status: int,
        headers: list[tuple[str, str]],
        body_chunks: list[bytes],
        respond: RespondFn,
    ) -> None:
        """Assemble and deliver the final response."""
        body = b"".join(body_chunks)
        if len(body) > self._max_body:
            log.error(f"ASGI response body ({len(body)} bytes) exceeds limit")
            respond(500, [("Content-Type", "text/plain")], b"Response too large")
            return

        has_content_length = any(
            k.lower() == "content-length" for k, _ in headers
        )
        if not has_content_length:
            headers.append(("Content-Length", str(len(body))))

        respond(status, headers, body)

    # ── Scope builder ──────────────────────────────────────────────────

    @staticmethod
    def _build_scope(request: Request) -> dict[str, Any]:
        """Build an ASGI 3.0 ``http`` scope from a :class:`Request`."""
        parsed = urlparse(request.url)
        path = unquote(parsed.path) or "/"
        query_string = parsed.query.encode("ascii", errors="replace")

        asgi_headers: list[tuple[bytes, bytes]] = []
        for key, value in request.headers:
            asgi_headers.append((
                key.lower().encode("latin-1"),
                value.encode("latin-1"),
            ))

        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": "http",
            "path": path,
            "query_string": query_string,
            "root_path": "",
            "headers": asgi_headers,
            "client": ("127.0.0.1", 0),
            "server": (parsed.hostname or "app", parsed.port or 0),
        }
