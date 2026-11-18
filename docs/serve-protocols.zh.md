# Serve 自定义协议（`lumiview://`）

通过 `WindowOptions(source=...)`，你可以直接利用自定义协议（默认 `lumiview://`）在本地托管前端构建产物或直接运行 Python Web 框架，**无需启动任何本地 HTTP 服务器、无需占用端口、无跨站访问风险**。

`lumiview.serve` 导出核心协议类型（`Request`、`Response`、`Serve`、`RespondFn`、
`Handler`）。文件 / WSGI / ASGI 适配器位于独立子模块，避免 `import lumiview` 或
`lumiview.serve` 时加载可选依赖：

```python
from lumiview.serve import Handler, Request, Response, Serve
from lumiview.serve.static import Static
from lumiview.serve.wsgi import WSGI
from lumiview.serve.asgi import ASGI
```

---

## 四种开箱即用的适配器

### 1. `Static` — 静态资源目录与 SPA 支持

适合打包后的 Vue / React / Svelte 等前端工程：

```python
from lumiview import Window, WindowOptions
from lumiview.serve.static import Static

# spa=True（默认）：找不到对应静态文件且路径无扩展名时，回退返回 index.html
win = await Window.create(
    WindowOptions(source=Static("frontend/dist", spa=True))
)
```

内置支持目录穿越防护、MIME 类型自动识别，以及 `ETag` / `Last-Modified` 缓存头。

### 2. `Handler` — 适配单个普通函数或协程

适合轻量级的自定义接口或虚拟文件响应：

```python
from lumiview.serve import Handler, Request, Response


async def my_api(req: Request) -> Response:
    return Response(
        status=200,
        headers=[("Content-Type", "application/json")],
        body=b'{"ok": true}',
    )


# 同步 def 函数（跑在线程池）与 async def 函数（跑在 asyncio 线程）均支持
api_source = Handler(my_api, scheme="api")
```

### 3. `WSGI` — 运行 Flask / Django 等同步 Web 应用

```python
from lumiview.serve.wsgi import WSGI

# 请求直接提交至 App 共享线程池（大小由 App(max_workers=...) 控制）
win = await Window.create(WindowOptions(source=WSGI(django_app)))
```

> **注意**：旧版的 `WSGI(..., max_workers=...)` 参数已废弃，统一复用应用级线程池。

### 4. `ASGI` — 运行 FastAPI / Starlette 等异步 Web 应用

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

## 组合多个自定义协议

`source` 可以传入一个列表，为不同适配器指定不同的 `scheme`（需符合 RFC 3986 协议名规范，且不可重复）：

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

- WebView 默认加载列表中**第一个** `source` 的 `<scheme>://app/`（上例为 `app://app/`）。
- 页面内可通过 `fetch("api://app/hello")` 直接请求第二个协议。

---

## 自定义 `Serve` 子类

若需完全掌控请求分发，可继承 `Serve` 并实现 `__call__(request, respond)`。**框架要求必须且仅调用一次 `respond(status, headers, body)`**（可同步调用，也可跨线程异步回调）：

```python
from lumiview.serve import Request, RespondFn, Serve


class CustomServe(Serve):
    def __init__(self) -> None:
        super().__init__(scheme="custom")

    def __call__(self, request: Request, respond: RespondFn) -> None:
        respond(200, [("Content-Type", "text/plain")], f"Path: {request.path}".encode())
```

---

## 使用限制（协议本质决定）

由于自定义协议走 WebView 底层资源拦截通道而非真实 TCP 套接字，存在以下限制：
- **不支持流式传输**：不支持 `StreamingResponse`、SSE（Server-Sent Events）与分块传输（Chunked Transfer），必须缓冲完整响应体后一次性返回（`ASGI`/`WSGI` 默认响应体上限为 10 MiB）。
- **不支持 WebSocket**：请使用 `Bridge`（`invoke` / `emit` / `listen`）替代实时双向推送。
- **不发送 ASGI Lifespan 事件**：框架启动与关闭钩子请使用 LumiView 的 `AppEvent.ReadyEvent` 与 `AppEvent.CloseRequestedEvent`。
