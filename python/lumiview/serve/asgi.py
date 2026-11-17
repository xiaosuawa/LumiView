"""ASGI adapter for ``lumiview://``.

.. warning::
   No streaming, SSE or WebSocket: the protocol calls ``respond()`` exactly once
   with the complete body. The request body is buffered and lifespan events are
   not emitted.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import unquote, urlparse

from lumiview.serve.base import Request, RespondFn, Serve

_log = logging.getLogger("lumiview.serve.asgi")


class ASGI(Serve):
    """Adapt an ASGI application to the :class:`~lumiview.serve.Serve` interface.

    Buffers the whole response (10 MiB default), times out after *timeout* seconds
    and answers at most once.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_body: int = 10 * 1024 * 1024,
        timeout: float = 30,
        scheme: str = "lumiview",
    ) -> None:
        super().__init__(scheme=scheme)
        self._app = app
        self._max_body = max_body
        self._timeout = timeout

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Handle one request on the App's asyncio loop; returns immediately."""
        from lumiview.app import App

        app = App.get()
        loop = app._async_loop
        if loop is None:
            respond(500, [("Content-Type", "text/plain")], b"App not running")
            return

        responded = False

        def _once(status: int, headers: list[tuple[str, str]], body: bytes) -> None:
            """Deliver the response exactly once — later calls are dropped."""
            nonlocal responded
            if responded:
                _log.warning(
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
                _log.error(f"ASGI app did not complete within {self._timeout:.1f}s")
                _once(504, [("Content-Type", "text/plain")], b"Gateway Timeout")
            except BaseException:
                _log.exception("ASGI app raised an exception")
                if app.is_running:
                    _once(500, [("Content-Type", "text/plain")], b"Internal Server Error")
                return

        if not app._spawn(_run()):
            # The loop closed between the check and the dispatch — answer 503.
            _log.warning("asyncio loop closed while dispatching an ASGI request")
            _once(503, [("Content-Type", "text/plain")], b"App is shutting down")

    async def _execute(self, request: Request, respond: RespondFn) -> None:
        """Run the ASGI app and deliver the response via ``respond()``."""
        scope = self._build_scope(request)

        status: int = 500
        headers: list[tuple[str, str]] = []
        body_chunks: list[bytes] = []
        finished = False

        async def receive() -> dict[str, Any]:
            return {
                "type": "http.request",
                "body": request.body,
                "more_body": False,
            }

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

        await self._app(scope, receive, send)

        if not finished:
            # No final body: answer here or the protocol callback hangs.
            _log.error("ASGI app returned without sending a final http.response.body")
            respond(500, [("Content-Type", "text/plain")], b"Internal Server Error")

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
            _log.error(f"ASGI response body ({len(body)} bytes) exceeds limit")
            respond(500, [("Content-Type", "text/plain")], b"Response too large")
            return

        has_content_length = any(k.lower() == "content-length" for k, _ in headers)
        if not has_content_length:
            headers.append(("Content-Length", str(len(body))))

        respond(status, headers, body)

    @staticmethod
    def _build_scope(request: Request) -> dict[str, Any]:
        """Build an ASGI 3.0 ``http`` scope from a :class:`Request`."""
        parsed = urlparse(request.url)
        path = unquote(parsed.path) or "/"
        query_string = parsed.query.encode("ascii", errors="replace")

        asgi_headers: list[tuple[bytes, bytes]] = []
        for key, value in request.headers:
            asgi_headers.append(
                (
                    key.lower().encode("latin-1"),
                    value.encode("latin-1"),
                )
            )

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
