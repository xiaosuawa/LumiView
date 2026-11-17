"""WSGI adapter for ``lumiview://``.

Streaming is not supported: call ``respond()`` once with the complete body.
"""

from __future__ import annotations

import io
import logging
import sys
import warnings
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlparse

from lumiview.serve.base import Request, RespondFn, Serve

_log = logging.getLogger("lumiview.serve.wsgi")


class WSGI(Serve):
    """Adapt a WSGI application to the :class:`Serve` interface.

    Runs on the App's shared thread pool; ``max_workers=`` is deprecated and ignored.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_workers: int | None = None,
        scheme: str = "lumiview",
    ) -> None:
        super().__init__(scheme=scheme)
        self._app = app
        if max_workers is not None:
            warnings.warn(
                "WSGI(max_workers=...) is deprecated and ignored — WSGI apps "
                "run on the App's shared thread pool; size it with "
                "App(max_workers=...).",
                DeprecationWarning,
                stacklevel=2,
            )

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Offload the request to the App's pool and return immediately."""
        from lumiview.app import App

        try:
            pool = App.get()._threadpool
        except RuntimeError:
            pool = None
        if pool is None:
            respond(503, [("Content-Type", "text/plain")], b"App is shutting down")
            return

        try:
            pool.submit(self._handle, request, respond)
        except RuntimeError:
            _log.warning("thread pool closed while dispatching a WSGI request")
            respond(503, [("Content-Type", "text/plain")], b"App is shutting down")

    def _handle(self, request: Request, respond: RespondFn) -> None:
        """Run the WSGI app and deliver the response via ``respond()``."""
        environ = self._build_environ(request, self.scheme)

        error_recalled = False

        def _send_error() -> None:
            """Send the best available error response (PEP 3333 error handling)."""
            if error_recalled and status_line:
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
        ) -> Callable[[bytes | str], None]:
            """PEP 3333 ``start_response`` — returns a ``write()`` callable."""
            nonlocal error_recalled
            if exc_info is not None:
                error_recalled = True
                status_line.clear()
                response_headers.clear()
            status_line.append(status)
            response_headers.extend(headers)

            def write(body_data: bytes | str) -> None:
                if isinstance(body_data, str):
                    body_data = body_data.encode("utf-8", errors="replace")
                body_chunks.append(body_data)

            return write

        try:
            result = self._app(environ, start_response)
        except Exception:
            _log.exception("WSGI app raised an exception")
            _send_error()
            return

        try:
            for chunk in result:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                body_chunks.append(chunk)
        except Exception:
            _log.exception("WSGI app iterable raised an exception")
            _send_error()
            return
        finally:
            if hasattr(result, "close"):
                try:
                    result.close()
                except Exception:
                    _log.exception("WSGI close() raised an exception")

        status_code = 500
        if status_line:
            try:
                status_code = int(status_line[0].split(" ", 1)[0])
            except (ValueError, IndexError):
                status_code = 500

        body = b"".join(body_chunks)

        max_body = 10 * 1024 * 1024
        if len(body) > max_body:
            respond(500, [("Content-Type", "text/plain")], b"Response too large")
            return

        has_content_length = any(
            k.lower() == "content-length" for k, _ in response_headers
        )
        if not has_content_length:
            response_headers.append(("Content-Length", str(len(body))))

        respond(status_code, response_headers, body)

    @staticmethod
    def _build_environ(request: Request, scheme: str) -> dict[str, Any]:
        parsed = urlparse(request.url)
        path = unquote(parsed.path) or "/"
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
            "wsgi.input": io.BytesIO(request.body),
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }

        if request.body:
            environ["CONTENT_LENGTH"] = str(len(request.body))

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
