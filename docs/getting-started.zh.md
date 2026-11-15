# 快速入门

LumiView 是一个「桌面窗口 + WebView」的 Python 运行时。你用 Python 写业务，
窗口、WebView 和原生外观在底层由 Rust 驱动。不需要 Rust 工具链、不需要 Node.js、
也没有 `tauri.conf.json`——`pip install` 就能用。

> **状态**：0.2.0rc1，alpha。API 尚未冻结，跨 minor 版本升级前请先看
> [变更日志](../CHANGELOG.md)。

## 环境要求

- Python 3.10+
- 系统 WebView：WebView2（Windows）、WKWebView（macOS）或 WebKitGTK（Linux）
- 仅 Linux：GTK 3 与 `libwebkit2gtk-4.1`

## 安装

```bash
pip install lumiview
```

## 第一个窗口

```python
import asyncio

from lumiview import App, Window, WindowOptions

app = App(name="Hello")


async def main() -> None:
    win = await Window.create(
        WindowOptions(
            title="Hello LumiView",
            width=900,
            height=640,
            html="<h1>Hello from LumiView!</h1>",
        )
    )

    await win.wait_loaded()
    print("page is ready")

    await asyncio.sleep(5)
    await win.close()


if __name__ == "__main__":
    app.run(main)
```

有三个点值得注意：

- `Window.create(...)` 返回 `Task[Window]`：异步代码里 `await`，同步代码里 `.result()`。
- `app.run(main)` 阻塞主线程直到应用退出。`main` 可以是 `async def`（跑在 asyncio 线程），
  也可以是普通函数（跑在线程池）。
- 默认 `exit_on_last_window=True`，最后一个窗口关闭时应用自动退出。

## 同步写法

同一套 API 不写 `async` 也能用。但 `app.run()` 要先启动事件循环、之后才能创建窗口，
所以入口必须传一个函数，并在里面用 `.result()` 阻塞：

```python
from lumiview import App, Window, WindowOptions

app = App(name="HelloSync")


def main() -> None:
    win = Window.create(WindowOptions(title="Sync", html="<p>hi</p>")).result()
    win.set_title("Sync — renamed").result()


app.run(main)
```

`main` 跑在线程池（不是 GUI 线程），这正是 `.result()` 安全的位置。

## 窗口配置：WindowOptions

所有窗口配置集中在一个可变 dataclass 里。`Window.create` 既接受 `WindowOptions`
对象，也接受同名字段作为关键字参数。

| 分组 | 字段 |
|---|---|
| 内容 | `url`、`html`、`source`（`Serve`，见 [serve.zh.md](serve.zh.md)）；`headers`、`user_agent`、`proxy`、`incognito`、`javascript`、`autoplay`、`clipboard`、`hotkeys_zoom`、`https_scheme`、`devtools` |
| 几何 | `width`、`height`、`position`、`monitor`、`min_size`、`max_size`、`maximized` |
| 外观 | `title`、`decorations`、`transparent`、`titlebar`（`TitleBarOptions`，macOS）、`undecorated_shadow`（Windows）、`theme`、`background_color`、`icon` |
| 行为 | `visible`、`focused`、`focusable`、`resizable`、`minimizable`、`maximizable`、`closable`、`always_on_top`、`always_on_bottom`、`visible_on_all_workspaces`、`content_protection`、`sync_visibility`、`close_behavior` |
| WebView 环境 | `data_directory`、`web_context`、`drag_drop`、`default_context_menus`、`back_forward_gestures` |
| IPC | `bridge`、`untrusted`（见 [plugins.zh.md](plugins.zh.md)、[js-client.zh.md](js-client.zh.md)） |
| 钩子 | `prepare`（见下文） |

同时给出多个内容来源时的优先级：`html=` 高于 `source=`，`url=` 高于 `source=`；
但 `source=` 注册的自定义协议仍然有效，页面里照样可以 `fetch("lumiview://...")`。

`untrusted=True` 会同时关闭两个方向：不注入客户端，也不解析收到的 IPC 消息；
详见 [js-client.zh.md](js-client.zh.md#untrustedtrue)。

配置的局部复用用 `dataclasses.replace`，模板用子类：

```python
from dataclasses import dataclass, replace

from lumiview import WindowOptions

base = WindowOptions(title="A", width=800)
wide = replace(base, width=1280)   # 新对象；base 不变


@dataclass
class AppOptions(WindowOptions):
    title: str = "MyApp"
    devtools: bool = True
```

`WindowOptions` 的子类**必须重新应用 `@dataclass`**——dataclass 生成的 `__init__`
在类创建时就把基类默认值固化了，不加装饰器的普通子类拿到的仍然是基类默认值。

## 事件

handler 按事件类注册，收到的是**事件对象**：

```python
from lumiview import WindowEvent

@win.on(WindowEvent.TitleChangedEvent)
def on_title(event):
    print("new title:", event.title)

@win.on(WindowEvent.NavigationRequestedEvent)
def on_navigation(event):
    if event.url.startswith("https://example.com"):
        event.prevent()          # 取消这次导航

@win.on(WindowEvent.JsEvent, where=lambda e: e.event == "data.changed")
async def on_js(event):
    print("from the page:", event.payload)
```

- handler 不在 GUI 线程运行：`async def` 进 asyncio 线程，普通 `def` 进线程池。
  不要在里面直接操作原生对象——用 `Window` 的方法（它们会自动切回 GUI 线程）。
- `where=` 就是一个 `(event) -> bool` 的过滤函数，在 handler 之前同步执行；
  过滤函数抛异常时按「不匹配」处理并记日志，不会中断派发。
- 可阻止事件：`CloseRequestedEvent`、`NavigationRequestedEvent`、
  `NewWindowRequestedEvent`、`DownloadStartedEvent`（后者还能 `save_to(path)`）。

`event.window` 指向事件所属的窗口。

### 可取消的订阅

`win.on(...)` / `app.on(...)` 返回一个 `Subscription`：它本身可调用，所以装饰器
写法不变，另带 `cancel()` 用来注销：

```python
sub = win.on(WindowEvent.TitleChangedEvent)


@sub
def on_title(event):
    print("new title:", event.title)


sub.cancel()   # 幂等
```

已经在派发中的事件仍可能再调用一次该 handler。

### 等待单个事件

`win.wait_for(...)` 返回一个 `Task`，命中下一个匹配事件后完成，并自动移除临时 handler：

```python
event = await win.wait_for(WindowEvent.ClosedEvent, timeout=10)
```

`app.wait_for(...)` 的形态相同。超时抛 `TimeoutError`；窗口或应用已经关闭时抛
`WindowClosedError` / `AppClosedError`。最常用的 `win.wait_loaded()` 就是它的封装，
并且是在 WebView 创建前注册的，不会漏事件。

`WindowEvent.ClosedEvent` 在原生窗口与 WebView 销毁后派发一次。此时
`win.is_closed` 为 `True`，窗口方法会抛 `WindowClosedError`；它适合做最终清理，
不适合再查询窗口状态。

### 在页面加载前注册 handler

`PageLoadStarted` / `PageLoadFinished` 可能在 `Window.create()` 返回之前就触发。
用 `prepare` 钩子拿到窗口空壳，提前注册：

```python
def prepare(win):
    win.on(WindowEvent.PageLoadStartedEvent)(
        lambda event: print("loading", event.url)
    )

win = await Window.create(WindowOptions(url="https://example.com", prepare=prepare))
```

## Task 与线程

所有跨线程/延迟操作都返回 `Task`——`concurrent.futures.Future` 的子类，三种用法：

```python
result = await handle                  # asyncio 线程
result = handle.result()               # 任意「非 GUI、非 asyncio」线程
handle.on_done(print)                  # 回调，不阻塞
handle.on_exception(lambda exc: ...)
```

- asyncio 代码里用 `await`，这是常规路径。
- 在 **asyncio 线程**上调用 `.result()` 会抛 `TaskDeadlockError`（否则会卡死事件循环）；
  在 GUI 线程上它会边等边泵命令队列——窗口会冻结，别放在热路径里。
- `task(fn, *args)` 把函数并发跑起来并包成 `Task`（`async` → asyncio 线程，`def` → 线程池）。
- `app.call_on_main(fn, ...)` 在主线程执行 `fn`，返回 `Task`。

完整模型见 [architecture.zh.md](architecture.zh.md)。

## 查询状态

下面这些是普通读取，任意线程都安全：

```python
from lumiview import App

app = App.get()

print(app.state)                  # AppState.RUNNING
print(app.windows)                # tuple[Window, ...] 快照
win = app.get_window(window_id)   # Window | None
print(win.id, win.is_closed)      # 稳定 id / 本地标志
print(app.is_async_thread())      # 当前是否在 asyncio 线程
print(app.async_loop)             # run() 前和关停期间为 None
```

`app.monitors()` / `app.primary_monitor()` 会访问原生事件循环，所以在 GUI 线程执行、
返回 `Task`：

```python
monitors = await app.monitors()
```

## 关闭流程

`close_behavior` 决定收到关闭请求后做什么：

- `CloseBehavior.Close`（默认）——销毁窗口；
- `CloseBehavior.Hide`——隐藏窗口（托盘类应用）；
- `CloseBehavior.Ignore`——什么都不做，由应用自己决定。

`CloseRequestedEvent` 先于上述行为执行，可以 `prevent()`：

```python
from lumiview import CloseBehavior, WindowEvent

win = await Window.create(WindowOptions(close_behavior=CloseBehavior.Hide))

@win.on(WindowEvent.CloseRequestedEvent)
def on_close(event):
    if not document_saved():
        event.prevent()      # 什么都不发生
```

`win.request_close()` 会走上面这条流程；`await win.close()` 跳过它，直接销毁窗口。

## 接下来

- [JS ↔ Python 桥](plugins.zh.md)——把 Python 函数暴露给页面。
- [菜单与托盘](menus.zh.md)——原生菜单栏与系统托盘。
- [JS 客户端参考](js-client.zh.md)——`window.__LUMIVIEW__` 与 npm 包。
- [前端托管](serve.zh.md)——静态文件、WSGI、ASGI 走 `lumiview://`。
- [架构](architecture.zh.md)——线程、Task、事件管线。
- [第三方集成](integrations.zh.md)——对话框、AppKit、GTK。
- [变更日志](../CHANGELOG.md)——0.2.0rc1 的破坏性变更与迁移表。
