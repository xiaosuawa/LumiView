# 前端托管（`lumiview://`）

`WindowOptions(source=...)` 会注册一个自定义协议，让 WebView 直接加载本地文件和前端应用，
不需要本地 HTTP 服务器。一个窗口可以注册多个协议（scheme）。

```python
from lumiview import Window, WindowOptions
from lumiview.serve import Static

win = await Window.create(WindowOptions(source=Static("frontend/dist")))
```

`Static("frontend/dist")` 注册默认 scheme `lumiview`，窗口加载 `lumiview://app/`
（host 固定为 `app`）。

## `Serve` 契约

处理器收到 `Request` 和 `respond` 回调，**必须恰好调用一次**
`respond(status, headers, body)`，返回值会被忽略。

```python
from lumiview.serve import Request, RespondFn, Serve


class Health(Serve):
    def __init__(self) -> None:
        super().__init__(scheme="lumiview")

    def __call__(self, request: Request, respond: RespondFn) -> None:
        respond(200, [("Content-Type", "text/plain")], b"ok")
```

`__call__` 跑在 GUI 线程，必须尽快返回。慢操作交给 `Handler`（派发到 asyncio 线程 /
线程池）或 `WSGI` / `ASGI` 适配器，它们自己管理线程。

### Request 与 Response

```python
@dataclass(frozen=True)
class Request:
    method: str                          # "GET"、"HEAD"……
    url: str                             # 完整的 app://app/... URL
    path: str                            # "/"、"/index.html"……
    query: str                           # 不含 "?"
    headers: list[tuple[str, str]]       # 保留重复键
    body: bytes

@dataclass
class Response:
    status: int = 200
    headers: list[tuple[str, str]] = []  # 保留重复键
    body: bytes = b""
```

## 适配器

### `Static`——静态文件与 SPA

```python
from lumiview.serve import Static

Static("frontend/dist")                    # SPA 回退（默认）
Static("frontend/dist", spa=False)         # 未知路径返回 404
Static("frontend/dist", scheme="app")      # 自定义 scheme
```

`spa=True` 时找不到文件就回退到 `index.html`，也就是前端路由的常规做法。
根目录在创建适配器时必须存在。

### `Handler`——普通函数

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

`async def` 处理器跑在 asyncio 线程，普通函数跑在线程池；抛异常会变成 `500` 响应。

### `WSGI` / `ASGI`——现有 Web 应用

```python
from lumiview.serve import ASGI, WSGI

WSGI(flask_app)                                   # Flask、Django……
WSGI(flask_app, max_workers=4, scheme="api")

ASGI(fastapi_app)                                 # FastAPI、Starlette……
ASGI(fastapi_app, max_body=10 * 1024 * 1024, timeout=30, scheme="api")
```

`WSGI` 在内部线程池运行（`max_workers=4`）；`ASGI` 在应用的 asyncio 线程运行
（`max_body` 默认 10 MB，`timeout` 默认 30 秒）。

## 多个 scheme

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

- 列表里的第一个就是窗口加载的地址（`app://app/`）。
- 同一个 scheme 注册两次会抛 `ValueError`。
- `url=` / `html=` 会覆盖加载内容，但协议仍然注册着。

### 跨 scheme 请求

同 scheme 的请求就是相对路径，所有平台都能用：

```js
const res = await fetch("/api/hello");
```

从页面访问**另一个** scheme 则与平台有关，因为 WebView2 只接受 `http(s)` URL：

| 平台 | scheme `app` 的页面 origin | scheme `api` 的地址 |
|---|---|---|
| Windows（默认 `https_scheme=True`） | `https://app.app/` | `https://api.app/hello` |
| Windows（`https_scheme=False`） | `http://app.app/` | `http://api.app/hello` |
| macOS / Linux | `app://app/` | `api://app/hello` |

Windows 上 WebView 会把 `<scheme>://<host>/` 映射成 `<https 或 http>://<scheme>.<host>/`。
跨 scheme 同时是跨源，所以处理器必须返回 `Access-Control-Allow-Origin`。

因此**优先用一个 scheme + 路径路由**（单个 `ASGI` 应用或 `Handler`，或者 `Static`
加同 scheme 的 `Handler`），除非确实需要独立 origin。

## 内容优先级

`Window.create` 决定首次加载的顺序：

1. `url=`——直接加载该地址；
2. `html=`——渲染字符串；
3. `source=`——加载 `<第一个 scheme>://app/`。

无论走哪条，`source=` 注册的协议都生效，所以用 `url=` 加载的页面同样可以访问它们
（受上面的跨源规则限制）。

## 常见坑

- `respond()` 必须恰好调用一次；调两次或不调都会让请求挂住。
- `Serve.__call__` 会阻塞 GUI 线程——只做轻量文件操作；慢的用 `Handler` / `ASGI`。
- `Static` 在构造时就解析根目录，目录不存在会立刻失败。
- 关停期间 asyncio 循环已经关闭：`Handler` 和 `ASGI` 会回 `503`
  （`App is shutting down`），而不是让请求一直挂着；自定义 `Serve` 仍需自己调用
  `respond()`。
- Windows 上页面 origin 是 `https://<scheme>.<host>`，尽管你写的是 `<scheme>://<host>`——
  前端代码里别硬编码 `app://`，用相对路径或从 `location` 推导。
