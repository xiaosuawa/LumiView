# Serve custom protocols (`lumiview://`)

With `WindowOptions(source=...)` you can serve frontend build output locally or run a
Python web framework directly over a custom protocol (default `lumiview://`) —
**no local HTTP server, no port to bind, no cross-site access risk**.

`lumiview.serve` exports the core protocol types (`Request`, `Response`, `Serve`,
`RespondFn`, `Handler`). The file / WSGI / ASGI adapters live in dedicated submodules so
that importing `lumiview` or `lumiview.serve` does not pull in optional machinery:

```python
from lumiview.serve import Handler, Request, Response, Serve
from lumiview.serve.static import Static
from lumiview.serve.wsgi import WSGI
from lumiview.serve.asgi import ASGI
```

---

## Four out-of-the-box adapters

### 1. `Static` — static asset directories and SPA support

Suited to bundled Vue / React / Svelte frontend projects:

```python
from lumiview import Window, WindowOptions
from lumiview.serve.static import Static

# spa=True (default): when no static file matches and the path has no extension, fall back to index.html
win = await Window.create(
    WindowOptions(source=Static("frontend/dist", spa=True))
)
```

Path traversal protection, automatic MIME type detection and `ETag` /
`Last-Modified` cache headers are built in.

### 2. `Handler` — adapt a single plain function or coroutine

Suited to lightweight custom endpoints or virtual file responses:

```python
from lumiview.serve import Handler, Request, Response


async def my_api(req: Request) -> Response:
    return Response(
        status=200,
        headers=[("Content-Type", "application/json")],
        body=b'{"ok": true}',
    )


# Both sync def functions (run on the thread pool) and async def functions (run on the asyncio thread) are supported
api_source = Handler(my_api, scheme="api")
```

### 3. `WSGI` — run synchronous web apps such as Flask / Django

```python
from lumiview.serve.wsgi import WSGI

# Requests are submitted straight to the App's shared thread pool (sized by App(max_workers=...))
win = await Window.create(WindowOptions(source=WSGI(django_app)))
```

> **Note**: the old `WSGI(..., max_workers=...)` argument is deprecated; the
> app-level thread pool is reused instead.

### 4. `ASGI` — run asynchronous web apps such as FastAPI / Starlette

```python
from fastapi import FastAPI
from lumiview.serve.asgi import ASGI

api = FastAPI()

@api.get("/hello")
async def hello():
    return {"msg": "Hello from FastAPI"}

win = await Window.create(
    WindowOptions(source=ASGI(api, max_body=10 * 1024 * 1024, timeout=30.0))
)
```

---

## Combining multiple custom protocols

`source` accepts a list, so each adapter can use its own `scheme` (it must follow
the RFC 3986 scheme-name rules and must not repeat):

```python
win = await Window.create(
    WindowOptions(
        source=[
            Static("frontend/dist", scheme="app"),
            ASGI(fastapi_app, scheme="api"),
        ]
    )
)
```

- The WebView loads `<scheme>://app/` for the **first** `source` in the list by
  default (`app://app/` in the example above).
- From the page, the second protocol can be requested directly with
  `fetch("api://app/hello")`.

---

## Custom `Serve` subclasses

For full control over request dispatch, subclass `Serve` and implement
`__call__(request, respond)`.
**The framework requires `respond(status, headers, body)` to be called exactly once**
(synchronously, or asynchronously from another thread):

```python
from lumiview.serve import Request, RespondFn, Serve


class CustomServe(Serve):
    def __init__(self) -> None:
        super().__init__(scheme="custom")

    def __call__(self, request: Request, respond: RespondFn) -> None:
        respond(200, [("Content-Type", "text/plain")], f"Path: {request.path}".encode())
```

---

## Limitations (inherent to the protocol)

Because custom protocols go through the WebView's low-level resource interception
channel instead of a real TCP socket, these limitations apply:

- **No streaming**: `StreamingResponse`, SSE (Server-Sent Events) and chunked
  transfer are unsupported; the full response body must be buffered and returned in
  one shot (the default `ASGI`/`WSGI` body limit is 10 MiB).
- **No WebSocket**: use `Bridge` (`invoke` / `emit` / `listen`) instead for
  real-time bidirectional push.
- **No ASGI lifespan events**: use LumiView's `AppEvent.ReadyEvent` and
  `AppEvent.CloseRequestedEvent` for framework startup and shutdown hooks.
