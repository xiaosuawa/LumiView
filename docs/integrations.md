# Third-Party Integrations

There is one rule: **anything that touches a native GUI object must run on the main
thread** — the thread that runs the tao event loop. Everything else is ordinary
Python.

LumiView already marshals its own calls for you: every `Window` method returns a
`Task` and runs on the main thread. For your own native code (dialogs, AppKit, GTK),
use `app.call_on_main(...)`.

```python
from lumiview import App

app = App.get()

handle = app.call_on_main(lambda: native_operation())   # -> Task
result = await handle                                   # async code
```

Where your code runs:

| Context | Thread |
|---|---|
| `app.run(entry)` with `async def` | asyncio thread |
| `app.run(entry)` with `def` | thread pool |
| `async def` event handler / bridge command | asyncio thread |
| `def` event handler / bridge command | thread pool |
| `app.call_on_main(fn)` | main thread |

`.result()` on a `Task` is only safe off the GUI and asyncio threads — inside an
`async` function use `await`.

## Inspecting app and window state

Plain reads are safe from any thread:

```python
from lumiview import App

app = App.get()

print(app.state)
print(app.windows)                 # tuple[Window, ...] snapshot
win = app.get_window(window_id)    # Window | None
print(win.id, win.is_closed)
print(app.is_async_thread())       # am I on the asyncio thread?
print(app.async_loop)              # None before run() and during shutdown
```

`app.async_loop` is the loop third-party threads may hand to
`asyncio.run_coroutine_threadsafe`; check it for `None` instead of racing
shutdown. `app.monitors()` / `app.primary_monitor()` touch the native event loop,
so they run on the GUI thread and return a `Task`.

## Native dialogs (tkinter, PySide6)

Dialogs are modal: they run their own event loop and block the tao loop until they
close. Open them on the main thread, then continue:

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

The same shape works for Qt (`QFileDialog`) and any other toolkit that requires the
GUI thread.

## macOS: AppKit / Cocoa (pyobjc)

AppKit is not thread-safe — calls outside the main thread can crash. Activate the
app or bring a window forward from the main thread:

```python
def _activate() -> None:
    from AppKit import NSApp

    NSApp.activateIgnoringOtherApps_(True)


await app.call_on_main(_activate)
```

## Linux: GTK

GTK objects belong to the thread that runs the GTK main loop — which is tao's main
thread. Create or mutate GTK objects only there:

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

## Work that is not GUI

File I/O, network calls, subprocesses, databases — no thread constraints, but keep
the asyncio loop free:

```python
import asyncio

from lumiview import WindowEvent, task


@win.on(WindowEvent.TitleChangedEvent)
async def on_title(event):
    # async handler: blocking work would stall the loop
    await asyncio.to_thread(write_report, event.title)

    # or schedule through the pool and get a Task back
    await task(write_report, event.title)
```

A *sync* handler already runs on the thread pool, so it may block:

```python
@win.on(WindowEvent.TitleChangedEvent)
def on_title_sync(event):
    write_report(event.title)      # thread pool — fine
```

## Updating the UI from background code

`Window` methods are safe from any thread and marshal themselves:

```python
async def on_title(event):
    await win.set_title(f"* {event.title}")
```

If you are on the main thread inside a callback and need the value *now*, don't call
`.result()` on a `Task` that needs the same thread — it would freeze the window.
Prefer `await` from asyncio code, or `call_on_main` from anywhere else.

During shutdown `call_on_main(...)` returns a failed `Task` (`AppClosedError`)
instead of queueing work the main thread will never drain.
