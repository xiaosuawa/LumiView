# `lumiview://` 自定义协议

`WindowOptions(source=...)` 注册自定义协议（默认 scheme 为 `lumiview`），页面通过 `lumiview://`（或自定义 scheme）加载本地内容——免起本地 HTTP 服务器。

## Serve 基类

`Serve` 是协议处理器的基类：构造时指定 `scheme`，`__call__` 收到 `Request` 和 `respond` 回调，**必须恰好调用一次** `respond(status, headers, body)`：

```python
from lumiview.serve import Serve, Request, RespondFn


class MyHandler(Serve):
    def __init__(self):
        super().__init__(scheme="lumiview")

    def __call__(self, request: Request, respond: RespondFn) -> None:
        respond(200, [("Content-Type", "text/plain")], b"hello")
```

日常直接用它提供的成品子类，不必手写 `__call__`。

## Handler —— 函数适配

普通函数（`fn(request) -> Response`）直接转成处理器：

```python
from lumiview.serve import Handler, Request, Response


def api(req: Request) -> Response:
    return Response(
        200,
        body=b'{"ok": true}',
        headers=[("Content-Type", "application/json")],
    )


handler = Handler(api, scheme="api")   # 注册到 api://
```

## Static —— 静态目录 + SPA

```python
from lumiview.serve import Static

# spa=True（默认）：找不到文件时回退到 index.html（单页应用路由）
static = Static("frontend/dist", scheme="app")
```

## WSGI / ASGI —— 现有 Web 应用

```python
from lumiview.serve import ASGI, WSGI

wsgi_source = WSGI(flask_app)               # Flask / Django 等
asgi_source = ASGI(fastapi_app)             # FastAPI / Starlette 等
```

- `WSGI(app, *, max_workers=4)` —— 同步应用跑在内部线程池；
- `ASGI(app, *, max_body=10MB, timeout=30)` —— 异步应用跑在 asyncio 线程。

## 注册进窗口

```python
from lumiview import App, Window, WindowOptions
from lumiview.serve import Handler, Request, Response, Static


def api(req: Request) -> Response:
    return Response(200, body=b'{"ok": true}')


async def main():
    win = await Window.create(WindowOptions(
        source=[
            Static("frontend/dist", scheme="app"),
            Handler(api, scheme="api"),
        ],
    ))   # 加载 app://app/；页面里可以 fetch("api://...")
```

规则：

- `source` 可以是单个 `Serve` 或列表；每个实例的 `scheme` 命名自己的协议（默认 `"lumiview"`）。
- 第一个 source 被加载为 `<scheme>://app/`。
- 优先级：`url=` > `html=` > `source`——但 `url` / `html` 只是**覆盖加载内容**，协议仍然注册（页面内仍可访问）。
- 重复 scheme 会报错。

## 页面内使用

```html
<script>
  const res = await fetch("api://hello");
  const data = await res.json();
</script>
```
