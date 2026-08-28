# 快速入门

## 安装

```bash
pip install lumiview
```

当前为 alpha 阶段，API 尚未完全冻结，升级时请留意变更。

## 最小应用

```python
import asyncio

from lumiview import App, Window, WindowOptions

app = App(name="MyApp")


async def main():
    win = await Window.create(WindowOptions(
        title="Hello",
        html="<h1>Hello from LumiView!</h1>",
    ))

    # 演示：5 秒后自动关闭。默认 exit_on_last_window=True，
    # 最后一个窗口关闭时应用自动退出。
    await asyncio.sleep(5)
    await win.close()


app.run(main)
```

要点：

- `Window.create(options)` 是 `@main_thread` 方法，返回 `Task[Window]` —— 异步代码里 `await`，同步代码里 `.result()`。
- `app.run(main)` 阻塞主线程直到应用退出；`main` 可以是异步函数（跑在 asyncio 线程）或同步函数（跑在线程池）。
- `html=` 直接渲染字符串；加载 URL 用 `url=`；加载本地目录用 `source=`（见 [serve.md](serve.md)）。

## 事件订阅

用 `win.on(事件类)` 装饰器注册 handler，handler 收到**事件对象**：

```python
from lumiview import App, Window, WindowOptions
from lumiview.events import WindowEvent


async def main():
    win = await Window.create(WindowOptions(
        title="Events",
        html="<p id='t'>hi</p>",
    ))

    @win.on(WindowEvent.TitleChangedEvent)
    def on_title(event):
        print("新标题:", event.title)

    @win.on(WindowEvent.NavigationRequestedEvent)
    def on_navigation(event):
        print("导航到:", event.url)
        if event.url.startswith("https://evil.com"):
            event.prevent()          # 阻止这次导航

    @win.on(WindowEvent.CloseRequestedEvent)
    def on_close(event):
        if not saved:
            event.prevent()          # 取消关闭
```

- 事件类集中在 `WindowEvent` 命名空间。
- 所有 handler 都运行在 **asyncio 线程**（不是主线程、不是 wryview 回调线程）——不要在里面直接操作原生 GUI。
- 可阻止事件（`CloseRequestedEvent` / `NavigationRequestedEvent` / `NewWindowRequestedEvent` / `DownloadStartedEvent`）调用 `event.prevent()` 后，默认行为会被取消。
- `event.window` 指向触发事件的窗口实例。

## 窗口配置：WindowOptions

所有配置集中在一个（可变的）dataclass 里，字段即 `create()` 的旧关键字参数：

| 字段 | 说明 |
|---|---|
| `title` / `width` / `height` | 标题与尺寸（逻辑像素） |
| `transparent` | 透明背景（配合 CSS `background: transparent`） |
| `decorations` | 原生标题栏与边框（自定义标题栏时设 `False`） |
| `devtools` | 启用浏览器开发者工具 |
| `visible` / `resizable` / `focused` | 可见 / 可缩放 / 聚焦 |
| `always_on_top` / `maximized` | 置顶 / 启动即最大化 |
| `close_behavior` | 关闭行为（见下文「关闭流程」） |
| `bridge` | `Bridge` 实例（JS ↔ Python IPC，见 [plugins.md](plugins.md)） |
| `untrusted` | 不注入任何初始化脚本（与 `bridge` 互斥） |
| `prepare` | 创建前钩子（见下文） |

局部修改用 `dataclasses.replace`；配置模板用**子类**：

```python
from dataclasses import dataclass, replace

base = WindowOptions(title="A", width=800)
opts = replace(base, width=1024)      # 新对象；base 不变


@dataclass(frozen=True)
class MyAppOptions(WindowOptions):
    title: str = "MyApp"
    devtools: bool = True


opts2 = MyAppOptions()                # title="MyApp", devtools=True
```

> **注意**：子类模板**必须重新应用 `@dataclass(...)`**（是否 `frozen` 自选）。dataclass 生成的 `__init__` 在生成时固化基类默认值——不加装饰器的普通子类继承到的仍是基类默认值（`"lumiview"`），类属性声明不会生效。

## `prepare` 钩子：注册早期事件

tao 窗口创建、webview 加载的那一刻事件流就开始了（`PageLoadStarted` 等可能立即触发），而 `win.on()` 通常只能在 `create()` 返回后调用。`prepare` 在 tao/webview 创建**之前**收到 Window 空壳实例（hooks 注册能力已就绪），可以提前订阅：

```python
def prepare(win):
    win.on(WindowEvent.PageLoadStartedEvent)(
        lambda event: print("开始加载:", event.url)
    )

win = await Window.create(WindowOptions(
    html="<h1>hi</h1>",
    prepare=prepare,
))
```

## 多窗口

多次调用 `Window.create` 即可；每个窗口有独立 id（`win._id`），应用内部以 `app._windows`（`dict[window_id, Window]`）跟踪。默认 `exit_on_last_window=True`，最后一个窗口关闭时应用退出；托盘类应用可设 `App(name=..., exit_on_last_window=False)`。

## 关闭流程

`CloseBehavior` 控制收到关闭请求时的行为：

- `CloseBehavior.Close`（默认）——销毁窗口；
- `CloseBehavior.Hide`——隐藏而不是销毁；
- `CloseBehavior.Ignore`——什么都不做。

`CloseRequestedEvent` 可在任何行为之前 `prevent()`：

```python
from lumiview import CloseBehavior

win = await Window.create(WindowOptions(
    close_behavior=CloseBehavior.Hide,   # 先隐藏
))


@win.on(WindowEvent.CloseRequestedEvent)
def on_close(event):
    if not saved:
        event.prevent()                    # 未保存 → 什么都不发生
```
