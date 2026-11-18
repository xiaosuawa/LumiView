"""Core types for ``lumiview://`` custom protocol handlers.

``Window.create(source=...)`` accepts one handler or a list (multiple schemes).

The built-in adapters live in dedicated submodules so importing this package stays
lightweight: :class:`lumiview.serve.static.Static`,
:class:`lumiview.serve.wsgi.WSGI` and :class:`lumiview.serve.asgi.ASGI`.
"""

from lumiview.serve.base import Request, Response, Serve, RespondFn, Handler


__all__ = [
    "Request",
    "Response",
    "RespondFn",
    "Serve",
    "Handler",
]
