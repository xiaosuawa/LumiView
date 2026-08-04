# 第三方集成

核心规则只有一条：**任何操作原生 GUI 的代码必须跑在主线程**（tao 事件循环线程）。事件 handler 运行在 asyncio 线程，第三方库的回调可能运行在任何线程——需要跨线程操作窗口时，统一走 `app.call_on_main(...)`。

```python
from lumiview import App

app = App.get()

handle = app.call_on_main(lambda: native_operation())   # → Task[T]
result = handle.result()                                 # 同步等待
```

## 1. pystray 系统托盘（macOS 案例）

macOS 上 `NSApplication` 是进程级单例，由 tao 创建。pystray 自己启动的 run 循环会与之冲突——**不要调用 `icon.run()` / `icon.run_detached()`**：状态栏 item 的呈现与事件由 tao 的主线程事件循环驱动，菜单回调里再调度回主线程。

```python
import pystray
from PIL import Image

from lumiview import App, Window, WindowOptions

app = App(name="TrayApp", exit_on_last_window=False)


def on_quit(icon, item):
    app.exit()


def on_toggle(icon, item):
    # 回调运行在状态栏事件线程 —— 原生操作调度回主线程
    app.call_on_main(lambda: win.set_title("toggled"))


icon = pystray.Icon(
    "tray",
    Image.new("RGBA", (64, 64), (0, 120, 215, 255)),
    menu=pystray.Menu(
        pystray.MenuItem("切换标题", on_toggle),
        pystray.MenuItem("退出", on_quit),
    ),
)
icon.visible = True          # 不调用 icon.run() / icon.run_detached()


async def main():
    global win
    win = await Window.create(WindowOptions(title="Tray"))
    # 关闭窗口不退出（exit_on_last_window=False）


app.run(main)
```

Windows / Linux 上 pystray 自带线程循环可用，但同样的主线程调度规则仍然适用：菜单回调里操作窗口一律 `app.call_on_main(...)`。

## 2. 原生对话框（tkinter / PySide6）

对话框属于 GUI 操作，必须在主线程创建；且阻塞式对话框会阻塞主线程事件循环，需要先关闭对话框再继续处理：

```python
import tkinter as tk

from lumiview import App

app = App.get()


def pick_file():
    root = tk.Tk()
    root.withdraw()
    path = tk.filedialog.askopenfilename()
    root.destroy()
    return path


# 在主线程弹对话框；期间 tao 事件循环被阻塞（模态），结束后恢复
path = app.call_on_main(pick_file).result()
```

## 3. AppKit / Cocoa 直接操作（macOS，pyobjc）

所有 AppKit 调用必须在主线程；在事件 handler 里直接操作会崩溃（NSWindow 非线程安全）：

```python
def bring_to_front():
    from AppKit import NSApp

    NSApp.activateIgnoringOtherApps_(True)


app.call_on_main(bring_to_front)
```

## 4. GTK 工具（Linux）

GTK 不是线程安全的：所有 GTK 调用（对话框、窗口操作、Clipboard 等）必须主线程。tao 的 GTK 主循环是唯一允许操作 GTK 对象的线程；从 handler 里调用前先 `app.call_on_main(...)`。

## 5. 无 UI 约束的系统 API

不触碰 GUI 的调用（截图、文件读写、网络请求、子进程等）没有线程约束——直接在事件 handler / 命令里跑即可（异步函数在 asyncio 线程，同步函数自动走线程池）：

```python
from lumiview import WindowEvent

@win.on(WindowEvent.TitleChangedEvent)   # win 来自 Window.create(...)
def on_title(evt):
    # 后台直接做：写日志、截图、上报……
    save_screenshot()          # 同步函数 → 线程池执行
```

如果要在同步 handler 里显式使用线程池，用 `lumiview.task.run_async`：

```python
from lumiview.task import run_async

# 在异步上下文里混合同步/异步回调
await run_async(sync_work, pool=app._threadpool)
```
