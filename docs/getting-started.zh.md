# 快速入门

## 环境要求与安装

- **Python >= 3.10**（同时支持 Free-threaded 无 GIL 构建，如 Python 3.14t / 3.15t）
- **操作系统与系统 WebView 运行时**：
  - **Windows**：WebView2（Windows 10/11 通常已内置）
  - **macOS**：系统自带 WKWebView
  - **Linux**：WebKitGTK（通常需安装 `libwebkit2gtk-4.1` 与 GTK3 运行时）

```bash
pip install lumiview
```

---

## 第一个应用

### 异步写法（推荐）

```python
from lumiview import App, Window, WindowOptions

app = App(name="HelloLumiView")


async def main():
    win = await Window.create(
        WindowOptions(
            title="Hello LumiView!",
            url="https://example.com",
            width=900,
            height=640,
            devtools=True,
        )
    )

    # 等待首屏加载完成（已在 create() 内部预注册，不会错过快速加载）
    await win.wait_loaded()

    # 在页面执行 JS 并获取返回值
    title = await win.eval_js("document.title")
    print("Page title:", title)


if __name__ == "__main__":
    app.run(main)
```

### 纯同步写法

LumiView 中所有跨线程操作都返回 `Task[T]`。如果你的入口函数是普通同步 `def`，只需在需要结果时调用 `.result()`：

```python
import time
from lumiview import App, Window

app = App(name="HelloSync")


def main():
    # Window.create 也支持直接传关键字参数
    win = Window.create(
        title="Hello Sync!",
        html="<h1>Hello LumiView!</h1>",
        width=800,
        height=600,
    ).result()

    win.wait_loaded().result()
    print(win.eval_js("document.querySelector('h1').textContent").result())

    time.sleep(2)
    win.load_url("https://www.python.org")


if __name__ == "__main__":
    app.run(main)
```

> **提示**：`app.run(main)` 会阻塞当前**主线程**运行原生事件循环，直到应用退出并返回退出码 `int`。`main` 若为 `async def` 会在内部的 asyncio 线程运行；若为普通 `def` 会在线程池运行。

---

## 页面内容来源

`WindowOptions` 支持三种内容来源，优先级为 **`url` > `html` > `source`**：

| 参数 | 说明 | 示例 |
|---|---|---|
| `url` | 加载远程或自定义协议 URL | `url="https://example.com"` |
| `html` | 直接渲染一段 HTML 字符串 | `html="<h1>Hi</h1>"` |
| `source` | 注册 `lumiview://` 自定义协议处理器（可传单个或列表） | `source=Static("dist")` |

即使同时传入了 `url` 或 `html` 覆盖初始页面，`source` 注册的自定义协议依然有效，页面内可通过 `fetch()` 访问。详见 [Serve 自定义协议](serve-protocols.zh.md)。

---

## 使用 `WindowOptions` 复用配置

`WindowOptions` 是一个可变的 `dataclass`，适合用 `dataclasses.replace` 微调配置，或通过继承来定义应用级配置模板：

```python
from dataclasses import dataclass, replace
from lumiview import WindowOptions

base = WindowOptions(width=1024, height=768, devtools=True)
secondary = replace(base, title="副窗口", width=600, height=400)


# 注意：继承 dataclass 时必须重新加上 @dataclass(kw_only=True) 装饰器，
# 否则子类覆盖的默认值不会生效。
@dataclass(kw_only=True)
class AppWindowOptions(WindowOptions):
    title: str = "MyApp"
    min_size: tuple[float, float] = (640, 480)
```

---

## 多窗口与共享 `WebContext`

多次调用 `await Window.create(...)` 即可创建多个窗口。通过 `app.windows` 可以获取当前所有打开窗口的快照，通过 `app.get_window(win.id)` 可以按 ID 查找窗口。

如果需要多个窗口共享同一套 Cookie、缓存与 `localStorage`，必须使用 `await WebContext.create(...)` 创建共享上下文（原生上下文绑定主线程，不能直接在模块顶层实例化 `wryview.WebContext`）：

```python
import tempfile
from lumiview import App, WebContext, Window, WindowOptions

app = App(name="MultiWindow", exit_on_last_window=True)
DATA_DIR = tempfile.mkdtemp(prefix="lumiview_")


async def main():
    ctx = await WebContext.create(data_directory=DATA_DIR)

    win_a = await Window.create(WindowOptions(title="窗口 A", url="https://example.com", web_context=ctx))
    win_b = await Window.create(WindowOptions(title="窗口 B", url="https://example.com", web_context=ctx))

    print("当前窗口 ID:", [w.id for w in app.windows])
```

- 默认 `exit_on_last_window=True`：最后一个窗口关闭时自动调用 `app.exit()`。
- 如果是驻留托盘的应用，可设置为 `App(exit_on_last_window=False)`。

---

## 开启诊断日志

LumiView 使用 Python 标准库 `logging`，所有日志归属在 `lumiview` 日志树下（如 `lumiview.app`、`lumiview.window`、`lumiview.bridge`、`lumiview.task`）：

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("lumiview").setLevel(logging.DEBUG)  # 查看任务调度、IPC 耗时与事件派发详情
```
