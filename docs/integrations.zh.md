# 第三方集成

只有一条规则：**任何操作原生 GUI 对象的代码都必须在主线程**——也就是运行 tao
事件循环的那个线程。其它一切都还是普通 Python。

LumiView 自己的调用已经帮你切好了：每个 `Window` 方法都返回 `Task` 并在主线程执行。
你自己的原生代码（对话框、AppKit、GTK）则用 `app.call_on_main(...)`：

```python
from lumiview import App

app = App.get()

handle = app.call_on_main(lambda: native_operation())   # -> Task
result = await handle                                   # 异步代码
```

你的代码跑在哪：

| 上下文 | 线程 |
|---|---|
| `app.run(entry)` 且 `async def` | asyncio 线程 |
| `app.run(entry)` 且 `def` | 线程池 |
| `async def` 事件 handler / 桥命令 | asyncio 线程 |
| `def` 事件 handler / 桥命令 | 线程池 |
| `app.call_on_main(fn)` | 主线程 |

只有在「非 GUI、非 asyncio」线程上调用 `Task.result()` 才安全——`async` 函数里请用 `await`。

## 查询应用与窗口状态

下面这些是普通读取，任意线程都安全：

```python
from lumiview import App

app = App.get()

print(app.state)
print(app.windows)                 # tuple[Window, ...] 快照
win = app.get_window(window_id)    # Window | None
print(win.id, win.is_closed)
print(app.is_async_thread())       # 当前是否在 asyncio 线程
print(app.async_loop)              # run() 前和关停期间为 None
```

`app.async_loop` 就是第三方线程可以交给 `asyncio.run_coroutine_threadsafe` 的循环；
先检查它是否为 `None`，不要和关停抢跑。`app.monitors()` / `app.primary_monitor()`
会访问原生事件循环，所以在 GUI 线程执行、返回 `Task`。

## 原生对话框（tkinter、PySide6）

对话框是模态的：它跑自己的事件循环，会把 tao 循环一起阻塞到关闭为止。
在主线程打开它，然后继续：

```python
def _pick_file() -> str | None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    path = tk.filedialog.askopenfilename()
    root.destroy()
    return path or None


async def pick_file() -> str | None:
    return await app.call_on_main(_pick_file)
```

Qt（`QFileDialog`）或任何要求 GUI 线程的工具包都是同样的形状。

## macOS：AppKit / Cocoa（pyobjc）

AppKit 不是线程安全的——在非主线程调用可能直接崩溃。把应用激活或窗口置前放到主线程：

```python
def _activate() -> None:
    from AppKit import NSApp

    NSApp.activateIgnoringOtherApps_(True)


await app.call_on_main(_activate)
```

## Linux：GTK

GTK 对象属于运行 GTK 主循环的线程，也就是 tao 的主线程。只在主线程创建或修改 GTK 对象：

```python
def _gtk_about() -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = Gtk.AboutDialog()
    dialog.run()
    dialog.destroy()


await app.call_on_main(_gtk_about)
```

## 非 GUI 的工作

文件读写、网络、子进程、数据库——没有线程限制，但别堵住 asyncio 线程：

```python
import asyncio

from lumiview import WindowEvent, task


@win.on(WindowEvent.TitleChangedEvent)
async def on_title(event):
    # async handler：阻塞操作会拖住事件循环
    await asyncio.to_thread(write_report, event.title)

    # 或者交给线程池，拿回一个 Task
    await task(write_report, event.title)
```

**同步** handler 本来就跑在线程池上，可以直接阻塞：

```python
from lumiview import WindowEvent


@win.on(WindowEvent.TitleChangedEvent)
def on_title_sync(event):
    write_report(event.title)      # 线程池——没问题
```

## 从后台代码更新界面

`Window` 的方法可以从任意线程调用，它们自己会切到主线程：

```python
async def on_title(event):
    await win.set_title(f"* {event.title}")
```

如果你已经在主线程的回调里、又需要立刻拿到值，不要对需要同一个线程的 `Task`
调 `.result()`——那会冻结窗口。异步代码里用 `await`，其它地方用 `call_on_main`。

关停期间 `call_on_main(...)` 会直接返回失败的 `Task`（`AppClosedError`），
而不是把工作排进主线程永远不会再处理的队列。
