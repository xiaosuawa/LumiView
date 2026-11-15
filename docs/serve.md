# Serving a Frontend (`lumiview://`)

`WindowOptions(source=...)` registers a custom protocol so the WebView can load local
files and web apps without a local HTTP server. One window can register several
protocols (schemes).

```python
from lumiview import Window, WindowOptions
from lumiview.serve import Static

win = await Window.create(WindowOptions(source=Static("frontend/dist")))
```

`Static("frontend/dist")` registers the default scheme `lumiview`, and the window
loads `lumiview://app/` (the host is always `app`).

## The `Serve` contract

A handler receives a `Request` and a `respond` callback, and **must call
`respond(status, headers, body)` exactly once**. The return value is ignored.

```python
from lumiview.serve import Request, RespondFn, Serve


class Health(Serve):
    def __init__(self) -> None:
        super().__init__(scheme="lumiview")

    def __call__(self, request: Request, respond: RespondFn) -> None:
        respond(200, [("Content-Type", "text/plain")], b"ok")
```

`__call__` runs on the GUI thread, so it must return quickly. For slow work use
`Handler` (dispatched to the asyncio loop / thread pool) or a `WSGI` / `ASGI`
adapter, which own their threading.

### Request and Response

```python
@dataclass(frozen=True)
class Request:
    method: str                          # "GET", "HEAD", ...
    url: str                             # full app://app/... URL
    path: str                            # "/", "/index.html", ...
    query: str                           # without "?"
    headers: list[tuple[str, str]]       # duplicates preserved
    body: bytes

@dataclass
class Response:
    status: int = 200
    headers: list[tuple[str, str]] = []  # duplicates preserved
    body: bytes = b""
```

## Adapters

### `Static` — files and SPAs

```python
from lumiview.serve import Static

Static("frontend/dist")                    # SPA fallback (default)
Static("frontend/dist", spa=False)         # 404 for unknown paths
Static("frontend/dist", scheme="app")      # custom scheme
```

`spa=True` serves `index.html` for paths that do not match a file — the usual
client-side-routing setup. The root directory must exist when the adapter is created.

### `Handler` — a plain function

```python
from lumiview.serve import Handler, Request, Response


def api(request: Request) -> Response:
    return Response(
        200,
        headers=[("Content-Type", "application/json")],
        body=b'{"ok": true}',
    )


Handler(api)                 # lumiview://app/...
Handler(api, scheme="api")   # api://app/...
```

`async def` handlers run on the asyncio loop, plain functions on the thread pool.
An exception becomes a `500` response.

### `WSGI` / `ASGI` — existing web apps

```python
from lumiview.serve import ASGI, WSGI

WSGI(flask_app)                                   # Flask, Django, ...
WSGI(flask_app, max_workers=4, scheme="api")

ASGI(fastapi_app)                                 # FastAPI, Starlette, ...
ASGI(fastapi_app, max_body=10 * 1024 * 1024, timeout=30, scheme="api")
```

`WSGI` runs the app in its own thread pool (`max_workers=4`); `ASGI` runs it on the
app's asyncio loop (`max_body` 10 MB, `timeout` 30 s).

## Multiple schemes

```python
from lumiview.serve import Handler, Request, Response, Static


def api(request: Request) -> Response:
    return Response(
        200,
        headers=[("Content-Type", "text/plain")],
        body=b"hello",
    )


win = await Window.create(WindowOptions(
    source=[
        Static("frontend/dist", scheme="app"),
        Handler(api, scheme="api"),
    ],
))
```

- The first entry in the list is what the window loads (`app://app/`).
- Registering the same scheme twice raises `ValueError`.
- `url=` / `html=` override what is loaded, but the protocols stay registered.

### Cross-scheme requests

Same-scheme requests are just relative URLs and work on every platform:

```js
const res = await fetch("/api/hello");
```

Reaching **another** scheme from the page is platform-dependent, because WebView2
only accepts `http(s)` URLs:

| Platform | Page origin for scheme `app` | URL for scheme `api` |
|---|---|---|
| Windows (default `https_scheme=True`) | `https://app.app/` | `https://api.app/hello` |
| Windows (`https_scheme=False`) | `http://app.app/` | `http://api.app/hello` |
| macOS / Linux | `app://app/` | `api://app/hello` |

The WebView maps `<scheme>://<host>/` to `<https or http>://<scheme>.<host>/` on
Windows. Cross-scheme requests are also cross-origin, so the handler must send
`Access-Control-Allow-Origin`.

Because of that, **prefer one scheme with path-based routing** (a single `ASGI` app
or `Handler`, or `Static` plus `Handler` under the same scheme) unless you really
need a separate origin.

## Content precedence

`Window.create` resolves the initial load in this order:

1. `url=` — load it directly;
2. `html=` — render the string;
3. `source=` — load `<first scheme>://app/`.

The protocols from `source=` are registered regardless, so a page loaded from `url=`
can still call them (subject to the cross-origin rules above).

## Gotchas

- Call `respond()` exactly once. Calling it twice, or never, hangs the request.
- `Serve.__call__` blocks the GUI thread — do file I/O there only if it is trivial;
  use `Handler` / `ASGI` for anything slow.
- `Static` resolves its root eagerly; a missing directory fails at construction.
- During shutdown the asyncio loop is closed: `Handler` and `ASGI` answer `503`
  (`App is shutting down`) instead of leaving the request pending. A custom
  `Serve` still has to call `respond()` itself.
- On Windows the page origin is `https://<scheme>.<host>` even though you wrote
  `<scheme>://<host>` — don't hardcode `app://` in frontend code; use relative URLs
  or derive the base from `location`.
