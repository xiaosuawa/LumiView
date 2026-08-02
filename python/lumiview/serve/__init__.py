"""
Serve — typed custom protocol handlers for ``lumiview://``.

Each adapter's ``scheme`` parameter names its custom protocol
(default ``"lumiview"``). ``Window.create(source=...)`` accepts one
Serve or a list — multiple protocols can be registered on one window.

Usage::

    from lumiview.serve import Static, WSGI, Handler, Request, Response

    # Serve a local directory
    win = await Window.create(source=Static("frontend/dist", spa=True))

    # Serve a WSGI app under a custom protocol name
    from myapp import app as wsgi_app
    win = await Window.create(
        source=WSGI(wsgi_app, scheme="api"),
    )

    # Serve a single-response handler
    win = await Window.create(source=Handler(lambda req: Response(body=b"hello")))

    # Register several protocols on one window
    win = await Window.create(
        source=[
            Static("frontend/dist", scheme="app"),
            Handler(my_api, scheme="api"),
        ],
    )  # loads app://app/; the page can fetch api://...
"""

from lumiview.serve.base import Request, Response, Serve, RespondFn, Handler
from lumiview.serve.static import Static
from lumiview.serve.wsgi import WSGI
from lumiview.serve.asgi import ASGI

__all__ = [
    "Request",
    "Response",
    "Serve",
    "Static",
    "WSGI",
    "ASGI",
    "Handler",
]
