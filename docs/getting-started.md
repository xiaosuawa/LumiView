# Getting Started

LumiView is a Python runtime for desktop windows with a WebView. You write Python;
the window, the WebView and the native chrome are Rust underneath. No Rust toolchain,
no Node.js, no `tauri.conf.json` — `pip install` and go.

> **Status:** 0.2.0rc1, alpha. The API is not frozen yet; read the
> [changelog](../CHANGELOG.md) before upgrading between minor versions.

## Requirements

- Python 3.10+
- A system WebView: WebView2 (Windows), WKWebView (macOS) or WebKitGTK (Linux)
- Linux only: GTK 3 and `libwebkit2gtk-4.1`

## Install

```bash
pip install lumiview
```

## Hello, window

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

Three things are worth noticing:

- `Window.create(...)` returns a `Task[Window]`, so you `await` it in async code and
  call `.result()` in sync code.
- `app.run(main)` blocks the main thread until the app exits. `main` may be an
  `async def` (runs on the asyncio thread) or a plain function (runs on the thread
  pool).
- Closing the last window exits the app by default (`exit_on_last_window=True`).

## The sync flavour

The same API works without `async`. `app.run()` starts the loop before any window
can be created, so pass a plain function as the entry point and block on each
`Task`:

```python
from lumiview import App, Window, WindowOptions

app = App(name="HelloSync")


def main() -> None:
    win = Window.create(WindowOptions(title="Sync", html="<p>hi</p>")).result()
    win.set_title("Sync — renamed").result()


app.run(main)
```

`main` runs on the thread pool (never the GUI thread), which is exactly where
`.result()` is safe.

## Window options

All window configuration is one mutable dataclass. `Window.create` accepts either a
`WindowOptions` object or the fields as keyword arguments.

| Group | Fields |
|---|---|
| Content | `url`, `html`, `source` (`Serve`, see [serve.md](serve.md)); `headers`, `user_agent`, `proxy`, `incognito`, `javascript`, `autoplay`, `clipboard`, `hotkeys_zoom`, `https_scheme`, `devtools` |
| Geometry | `width`, `height`, `position`, `monitor`, `min_size`, `max_size`, `maximized` |
| Chrome | `title`, `decorations`, `transparent`, `titlebar` (`TitleBarOptions`, macOS), `undecorated_shadow` (Windows), `theme`, `background_color`, `icon` |
| Behaviour | `visible`, `focused`, `focusable`, `resizable`, `minimizable`, `maximizable`, `closable`, `always_on_top`, `always_on_bottom`, `visible_on_all_workspaces`, `content_protection`, `sync_visibility`, `close_behavior` |
| WebView env | `data_directory`, `web_context`, `drag_drop`, `default_context_menus`, `back_forward_gestures` |
| IPC | `bridge`, `untrusted` (see [plugins.md](plugins.md), [js-client.md](js-client.md)) |
| Hook | `prepare` (see below) |

Content precedence when several are given: `html=` wins over `source=`, `url=`
wins over `source=`. The custom protocol from `source=` is registered either way,
so the page can still `fetch("lumiview://...")`.

`untrusted=True` disables IPC in both directions — nothing is injected and
incoming messages are not parsed; see [js-client.md](js-client.md#untrustedtrue).

Reuse and tweak options with `dataclasses.replace`; subclass them for templates:

```python
from dataclasses import dataclass, replace

from lumiview import WindowOptions

base = WindowOptions(title="A", width=800)
wide = replace(base, width=1280)   # new object; `base` is untouched


@dataclass
class AppOptions(WindowOptions):
    title: str = "MyApp"
    devtools: bool = True
```

A `WindowOptions` subclass must re-apply `@dataclass` — the generated `__init__`
captures base defaults at class-creation time.

## Events

Handlers are registered per event class and receive the event object:

```python
from lumiview import WindowEvent

@win.on(WindowEvent.TitleChangedEvent)
def on_title(event):
    print("new title:", event.title)

@win.on(WindowEvent.NavigationRequestedEvent)
def on_navigation(event):
    if event.url.startswith("https://example.com"):
        event.prevent()          # cancel this navigation

@win.on(WindowEvent.JsEvent, where=lambda e: e.event == "data.changed")
async def on_js(event):
    print("from the page:", event.payload)
```

- Handlers run off the GUI thread: `async def` on the asyncio loop, `def` on the
  thread pool. Never touch native window objects directly — use `Window` methods
  (they marshal to the GUI thread).
- `where=` is a plain `(event) -> bool` filter function, run inline before the
  handler. A filter that raises is treated as a non-match and logged — it never
  breaks dispatch.
- Preventable events: `CloseRequestedEvent`, `NavigationRequestedEvent`,
  `NewWindowRequestedEvent`, `DownloadStartedEvent` (the last one can also
  `save_to(path)`).

`event.window` is the `Window` the event belongs to.

### Subscriptions

`win.on(...)` and `app.on(...)` return a `Subscription`: a callable, so the
decorator form still works, with an extra `cancel()` to unregister:

```python
sub = win.on(WindowEvent.TitleChangedEvent)


@sub
def on_title(event):
    print("new title:", event.title)


sub.cancel()   # idempotent
```

A dispatch already in flight may still reach the handler once after `cancel()`.

### Waiting for one event

`win.wait_for(...)` returns a `Task` that resolves with the next matching event and
removes its temporary handler:

```python
event = await win.wait_for(WindowEvent.ClosedEvent, timeout=10)
```

`app.wait_for(...)` has the same shape. Waiters fail with `TimeoutError` on
timeout and `WindowClosedError` / `AppClosedError` if the window/app is already
gone. `win.wait_loaded()` is the common case: it waits for
`PageLoadFinishedEvent` and is registered before the WebView exists, so it cannot
miss the event.

`WindowEvent.ClosedEvent` fires once after the native window and WebView are
destroyed. At that point `win.is_closed` is `True` and window methods raise
`WindowClosedError`; use the event for final cleanup, not for querying the window.

### Registering handlers *before* the page loads

`PageLoadStarted` / `PageLoadFinished` can fire before `Window.create()` returns.
Use the `prepare` hook to register nothing-missable handlers on the window shell:

```python
def prepare(win):
    win.on(WindowEvent.PageLoadStartedEvent)(
        lambda event: print("loading", event.url)
    )

win = await Window.create(WindowOptions(url="https://example.com", prepare=prepare))
```

## Tasks and threads

Everything that crosses a thread returns `Task` — a `concurrent.futures.Future`
subclass with three consumption styles:

```python
result = await handle                  # asyncio thread
result = handle.result()               # any non-GUI, non-asyncio thread
handle.on_done(print)                  # callback, no blocking
handle.on_exception(lambda exc: ...)
```

- `await` from asyncio code is the normal path.
- `.result()` from the **asyncio thread** raises `TaskDeadlockError` (it would
  deadlock the loop). From the GUI thread it drains the command queue while
  waiting — the window freezes meanwhile, so don't do it in a hot path.
- `task(fn, *args)` runs a function concurrently and wraps the result in a `Task`
  (`async` → asyncio loop, `def` → thread pool).
- `app.call_on_main(fn, ...)` runs `fn` on the GUI thread and returns a `Task`.

Full model: [architecture.md](architecture.md).

## Inspecting state

These are plain reads, safe from any thread:

```python
from lumiview import App

app = App.get()

print(app.state)                  # AppState.RUNNING
print(app.windows)                # tuple[Window, ...] snapshot
win = app.get_window(window_id)   # Window | None
print(win.id, win.is_closed)      # stable id / local flag
print(app.is_async_thread())      # am I on the asyncio thread?
print(app.async_loop)             # None before run() and during shutdown
```

`app.monitors()` and `app.primary_monitor()` touch the native event loop, so they
run on the GUI thread and return a `Task`:

```python
monitors = await app.monitors()
```

## Closing

`close_behavior` decides what a close request does:

- `CloseBehavior.Close` (default) — destroy the window;
- `CloseBehavior.Hide` — hide it instead (tray apps);
- `CloseBehavior.Ignore` — do nothing, let the app decide.

`CloseRequestedEvent` runs first and can `prevent()` any of them:

```python
from lumiview import CloseBehavior, WindowEvent

win = await Window.create(WindowOptions(close_behavior=CloseBehavior.Hide))

@win.on(WindowEvent.CloseRequestedEvent)
def on_close(event):
    if not document_saved():
        event.prevent()      # nothing happens
```

`win.request_close()` goes through that flow; `await win.close()` skips it and
destroys the window immediately.

## Where to go next

- [JS ↔ Python bridge](plugins.md) — expose Python functions to the page.
- [Menus & tray icons](menus.md) — native menu bars and the system tray.
- [JS client reference](js-client.md) — `window.__LUMIVIEW__` and the npm package.
- [Serving a frontend](serve.md) — static files, WSGI, ASGI over `lumiview://`.
- [Architecture](architecture.md) — threads, tasks, event pipeline.
- [Third-party integrations](integrations.md) — dialogs, AppKit, GTK.
- [Changelog](../CHANGELOG.md) — breaking changes and migration from 0.1.2.
