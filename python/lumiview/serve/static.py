"""
Static file serving from a local directory.

Supports directory traversal protection, MIME detection, SPA fallback,
and ETag/Last-Modified headers.
"""

from __future__ import annotations

import mimetypes
import os
import posixpath
import time
from pathlib import Path
from urllib.parse import unquote

from lumiview.serve.base import Request, RespondFn, _check_scheme

mimetypes.init()


class Static:
    """Serve files from a local directory.

    Parameters:
        root: Filesystem path to the document root.
        spa: If ``True``, requests for paths without a file extension
            that accept ``text/html`` are served ``index.html`` instead
            (SPA history-mode fallback).
        scheme: Name of the custom protocol this directory is served
            under (default ``"lumiview"``).

    Usage::

        source = Static("frontend/dist", spa=True)
        source = Static("frontend/dist", scheme="app")
    """

    def __init__(
        self,
        root: str | Path,
        *,
        spa: bool = True,
        scheme: str = "lumiview",
    ) -> None:
        self._root = Path(root).resolve(strict=True)
        self._spa = spa
        self.scheme = _check_scheme(scheme)

    # ── Serve ──────────────────────────────────────────────────────────────

    def __call__(self, request: Request, respond: RespondFn) -> None:
        """Handle one request (sync — file I/O is fast enough for GUI thread)."""
        path = request.path or "/"

        safe_path = self._safe_path(path)
        if safe_path is None:
            respond(400, [], b"Bad Request")
            return

        content, mtime = self._read_file(safe_path)
        if content is not None:
            status, headers = self._file_response(safe_path, content, mtime)
            respond(status, headers, content)
            return

        # SPA fallback: client-side routes → index.html
        if self._spa and _is_spa_candidate(path):
            content, mtime = self._read_file("index.html")
            if content is not None:
                status, headers = self._file_response("index.html", content, mtime)
                respond(status, headers, content)
                return

        respond(404, [], b"Not Found")

    # ── Internal ───────────────────────────────────────────────────────────

    def _safe_path(self, path: str) -> str | None:
        """Normalize and validate a request path.  Returns a relative path
        string like ``"index.html"`` or ``"js/app.js"``, or ``None``."""
        try:
            decoded = unquote(path)
        except Exception:
            return None

        normalized = posixpath.normpath(decoded).lstrip("/")
        if normalized.startswith("..") or os.path.isabs(normalized):
            return None
        if not normalized:
            return "index.html"
        return normalized

    def _read_file(self, rel_path: str) -> tuple[bytes | None, int | None]:
        """Read a file from disk.  Returns ``(content, mtime)`` or ``(None, None)``."""
        full = self._root / rel_path
        try:
            full = full.resolve(strict=False)
            full.relative_to(self._root)
        except ValueError:
            return None, None

        if not full.is_file():
            return None, None

        try:
            mtime = int(full.stat().st_mtime)
            return full.read_bytes(), mtime
        except OSError:
            return None, None

    def _file_response(
        self,
        rel_path: str,
        content: bytes,
        mtime: int | None,
    ) -> tuple[int, list[tuple[str, str]]]:
        """Build status + headers with Content-Type and caching."""
        mime_type, _ = mimetypes.guess_type(rel_path)
        headers: list[tuple[str, str]] = [
            ("Content-Type", mime_type or "application/octet-stream"),
            ("Content-Length", str(len(content))),
        ]
        if mtime:
            headers.append(("ETag", f'"{mtime:x}"'))
            headers.append(("Last-Modified", _http_date(mtime)))
        return 200, headers


# ── Helpers ─────────────────────────────────────────────────────────────────


def _is_spa_candidate(path: str) -> bool:
    """True if the path looks like a client-side route (no file extension)."""
    clean = path.split("?")[0].split("#")[0]
    _, ext = posixpath.splitext(clean)
    return not ext


def _http_date(timestamp: int) -> str:
    """Format a Unix timestamp as an HTTP-date (RFC 7231)."""
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(timestamp))
