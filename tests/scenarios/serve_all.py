from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from lumiview import App, Window, WindowOptions
from lumiview.serve import ASGI, Handler, Response, Static, Request, WSGI


def _handler(_req: Request):
    return Response(
        status=200,
        headers=[("Content-Type", "text/html")],
        body=b"<html><body><h1>from-handler</h1></body></html>",
    )


def _wsgi_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/html")])
    return [b"<html><body><h1>from-wsgi</h1></body></html>"]


async def _asgi_app(scope, receive, send):
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/html")],
    })
    await send({
        "type": "http.response.body",
        "body": b"<html><body><h1>from-asgi</h1></body></html>",
    })


async def _entry() -> None:
    root = Path(tempfile.mkdtemp(prefix="lumiview-static-"))
    (root / "index.html").write_text(
        "<html><body><h1>from-static</h1></body></html>", encoding="utf-8"
    )

    specs = [
        ("handler", Handler(_handler, scheme="handler"), "from-handler"),
        ("static", Static(root, scheme="static"), "from-static"),
        ("wsgi", WSGI(_wsgi_app, scheme="wsgi"), "from-wsgi"),
        ("asgi", ASGI(_asgi_app, scheme="asgi"), "from-asgi"),
    ]

    # One window at a time: the four adapters are what this scenario
    # verifies, and holding four simultaneous WebView2 instances on a
    # busy machine can stall engine creation. `multi_window` covers the
    # simultaneous case.
    for name, source, expect in specs:
        print(f"[scenario] {name}: create", flush=True)
        win = await Window.create(WindowOptions(
            source=source,
            visible=False,
        ))
        try:
            print(f"[scenario] {name}: wait_loaded", flush=True)
            await win.wait_loaded(timeout=30)
            print(f"[scenario] {name}: eval_js", flush=True)
            val = await win.eval_js("document.querySelector('h1').textContent")
            assert expect in str(val), f"{name}: {expect} -> {val!r}"
        finally:
            print(f"[scenario] {name}: close", flush=True)
            await win.close()

    assert len(App.get()._windows) == 0, (
        f"windows leaked: {len(App.get()._windows)}"
    )
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
