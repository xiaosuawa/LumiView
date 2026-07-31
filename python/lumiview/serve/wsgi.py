"""
WSGI adapter — run a WSGI application inside a ``lumiview://`` custom protocol.

This is a compatibility adapter.  New projects should prefer :class:`Static`
+ :class:`Bridge` for better performance and type safety.

.. warning::

    Streaming responses (chunked transfer encoding, Server-Sent Events,
    long-polling, etc.) **will not work** through the ``lumiview://``
    custom protocol.  The protocol delivers one complete response — the
    handler must call ``respond()`` exactly once with the full body.
    Streaming requires a real HTTP server.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from lumiview.serve.base import Request, RespondFn, _check_scheme

log = logging.getLogger("lumiview.serve.wsgi")


class WSGI:
    """Adapt a WSGI application to the :class:`Serve` protocol.

    Parameters:
        app: A WSGI callable (``environ, start_response -> body_iterable``).
        max_workers: Thread pool size for executor isolation.
            WSGI apps run in a dedicated thread pool to avoid blocking
            the custom protocol callback thread.
        scheme: Name of the custom protocol this app is served under
            (default ``"lumiview"``).

    Usage::

        from flask import Flask
        flask_app = Flask(__name__)

        win = await Window.create(source=WSGI(flask_app))

    .. note::
        WSGI is a synchronous protocol.  Async Python web frameworks
        are not supported through this adapter.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_workers: int = 4,
        scheme: str = "lumiview",
    ) -> None:
        self._app = app
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="lumiview-wsgi",
        )
        self.scheme = _check_scheme(scheme)

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Handle a request — offloads to the thread pool and returns immediately.

        The wsgi app runs on a thread pool thread and calls ``respond()`` when done.
        """
        self._pool.submit(self._handle, request, respond)

    def _handle(self, request: Request, respond: RespondFn) -> None:
        """Run the WSGI app and deliver the response via ``respond()``."""
        environ = self._build_environ(request, self.scheme)

        def _send_error() -> None:
            """Send the best available error response.

            If ``start_response`` was called (with or without ``exc_info``)
            we use the status/headers it set.  Otherwise fall back to 500.
            """
            if status_line:
                code = 500
                try:
                    code = int(status_line[0].split(" ", 1)[0])
                except (ValueError, IndexError):
                    pass
                respond(code, list(response_headers), b"Internal Server Error")
            else:
                respond(500, [("Content-Type", "text/plain")], b"Internal Server Error")
        status_line: list[str] = []
        response_headers: list[tuple[str, str]] = []
        body_chunks: list[bytes] = []

        def start_response(
                status: str,
                headers: list[tuple[str, str]],
                exc_info: Any = None,
        ) -> None:
            if exc_info is not None:
                status_line.clear()
                response_headers.clear()
            status_line.append(status)
            response_headers.extend(headers)

        try:
            result = self._app(environ, start_response)
        except Exception:
            log.exception("WSGI app raised an exception")
            _send_error()
            return

        try:
            for chunk in result:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                body_chunks.append(chunk)
        except Exception:
            log.exception("WSGI app iterable raised an exception")
            _send_error()
            return
        finally:
            if hasattr(result, "close"):
                try:
                    result.close()
                except Exception:
                    log.exception("WSGI close() raised an exception")

        # Parse status line: "200 OK" → 200
        status_code = 500
        if status_line:
            try:
                status_code = int(status_line[0].split(" ", 1)[0])
            except (ValueError, IndexError):
                status_code = 500

        body = b"".join(body_chunks)

        # Enforce response size limit (10 MB).
        max_body = 10 * 1024 * 1024
        if len(body) > max_body:
            respond(500, [("Content-Type", "text/plain")], b"Response too large")
            return

        # Ensure Content-Length is present.
        has_content_length = any(
            k.lower() == "content-length" for k, _ in response_headers
        )
        if not has_content_length:
            response_headers.append(("Content-Length", str(len(body))))

        respond(status_code, response_headers, body)

    # ── WSGI environ ───────────────────────────────────────────────────────

    @staticmethod
    def _build_environ(request: Request, scheme: str) -> dict[str, Any]:
        parsed = urlparse(request.url)
        path = parsed.path or "/"
        query = parsed.query or ""

        environ: dict[str, Any] = {
            "REQUEST_METHOD": request.method,
            "SCRIPT_NAME": "",
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "lumiview",
            "SERVER_PORT": "0",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": scheme,
            "wsgi.input": _BytesIO(request.body),
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }

        if request.body:
            environ["CONTENT_LENGTH"] = str(len(request.body))

        # Headers → WSGI HTTP_* convention
        content_type = None
        for key, value in request.headers:
            if key.lower() == "content-type":
                content_type = value
            wsgi_key = "HTTP_" + key.upper().replace("-", "_")
            if wsgi_key not in ("HTTP_CONTENT_TYPE", "HTTP_CONTENT_LENGTH"):
                environ[wsgi_key] = value
        if content_type is not None:
            environ["CONTENT_TYPE"] = content_type

        return environ


class _BytesIO:
    """Minimal BytesIO wrapper for wsgi.input."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos: self._pos + size]
        self._pos += size
        return chunk

    def readline(self) -> bytes:
        idx = self._data.find(b"\n", self._pos)
        if idx < 0:
            return self.read()
        return self.read(idx - self._pos + 1)
