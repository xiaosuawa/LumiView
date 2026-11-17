# Getting started

## Requirements and installation

- **Python >= 3.10** (free-threaded builds without the GIL are supported too, such as Python 3.14t / 3.15t)
- **Operating system and system WebView runtime**:
  - **Windows**: WebView2 (usually bundled with Windows 10/11)
  - **macOS**: the system WKWebView
  - **Linux**: WebKitGTK (usually requires installing `libwebkit2gtk-4.1` and the GTK3 runtime)

```bash
pip install lumiview
```

---

## Your first app

### Async style (recommended)

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

    # Wait for the initial page load (pre-registered inside create(), so a fast load is not missed)
    await win.wait_loaded()

    # Run JS in the page and get the return value
    title = await win.eval_js("document.title")
    print("Page title:", title)


if __name__ == "__main__":
    app.run(main)
```

### Pure sync style

Every cross-thread operation in LumiView returns a `Task[T]`. If your entry function is a plain synchronous `def`, just call `.result()` where you need the value:

```python
import time
from lumiview import App, Window

app = App(name="HelloSync")


def main():
    # Window.create also accepts keyword arguments directly
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

> **Tip**: `app.run(main)` blocks the current **main thread** while it runs the native event loop, and returns the exit code as an `int` once the app exits. An `async def` `main` runs on the internal asyncio thread; a plain `def` runs on the thread pool.

---

## Page content sources

`WindowOptions` accepts three content sources, in priority order **`url` > `html` > `source`**:

| Option | Description | Example |
|---|---|---|
| `url` | Loads a remote or custom-protocol URL | `url="https://example.com"` |
| `html` | Renders an HTML string directly | `html="<h1>Hi</h1>"` |
| `source` | Registers a `lumiview://` custom protocol handler (a single handler or a list) | `source=Static("dist")` |

Even when `url` or `html` overrides the initial page, the custom protocol registered by `source` stays active and the page can reach it through `fetch()`. See [Serve custom protocols](serve-protocols.md) for details.

---

## Reusing configuration with `WindowOptions`

`WindowOptions` is a mutable `dataclass`, handy for tweaking a configuration with `dataclasses.replace` or for defining app-level templates through inheritance:

```python
from dataclasses import dataclass, replace
from lumiview import WindowOptions

base = WindowOptions(width=1024, height=768, devtools=True)
secondary = replace(base, title="Secondary window", width=600, height=400)


# Note: a dataclass subclass must re-apply the @dataclass(kw_only=True)
# decorator, otherwise the defaults overridden by the subclass do not apply.
@dataclass(kw_only=True)
class AppWindowOptions(WindowOptions):
    title: str = "MyApp"
    min_size: tuple[float, float] = (640, 480)
```

---

## Multiple windows and a shared `WebContext`

Call `await Window.create(...)` more than once to open several windows. `app.windows` gives you a snapshot of every open window, and `app.get_window(win.id)` looks one up by ID.

If several windows must share the same cookies, cache and `localStorage`, create a shared context with `await WebContext.create(...)` (the native context is bound to the main thread, so never instantiate `wryview.WebContext` directly at module level):

```python
import tempfile
from lumiview import App, WebContext, Window, WindowOptions

app = App(name="MultiWindow", exit_on_last_window=True)
DATA_DIR = tempfile.mkdtemp(prefix="lumiview_")


async def main():
    ctx = await WebContext.create(data_directory=DATA_DIR)

    win_a = await Window.create(WindowOptions(title="Window A", url="https://example.com", web_context=ctx))
    win_b = await Window.create(WindowOptions(title="Window B", url="https://example.com", web_context=ctx))

    print("Window IDs:", [w.id for w in app.windows])
```

- `exit_on_last_window=True` is the default: closing the last window calls `app.exit()` automatically.
- Tray-resident apps can pass `App(exit_on_last_window=False)` instead.

---

## Enabling diagnostic logging

LumiView uses the standard-library `logging` module, and every record lives under the `lumiview` logger tree (`lumiview.app`, `lumiview.window`, `lumiview.bridge`, `lumiview.task`, and so on):

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("lumiview").setLevel(logging.DEBUG)  # show task scheduling, IPC timing and event dispatch details
```
