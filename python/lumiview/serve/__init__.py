"""Typed custom protocol handlers for ``lumiview://``.

``Window.create(source=...)`` accepts one handler or a list (multiple schemes).
"""

from lumiview.serve.base import Request, Response, Serve, RespondFn, Handler
from lumiview.serve.static import Static
from lumiview.serve.wsgi import WSGI
from lumiview.serve.asgi import ASGI

__all__ = [
    "Request",
    "Response",
    "RespondFn",
    "Serve",
    "Static",
    "WSGI",
    "ASGI",
    "Handler",
]
