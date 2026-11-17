# Application lifecycle and events

## The `App` state machine and graceful shutdown

`App` is a single global instance (reachable through `App.get()`), and its lifecycle
only moves forward:

```text
CREATED ──(app.run)──▶ RUNNING ──(native loop exits)──▶ STOPPED
```

Read the current phase from `app.state`, `app.is_running` and `app.is_stopped`.

### Two-phase shutdown

A close starts when you call `app.exit(code=0)`, when the last window closes
(`exit_on_last_window=True`), when `Ctrl+C` is pressed, or on macOS when you press
`Cmd+Q`. The close runs in two phases:

1. **Negotiation phase (`AppEvent.CloseRequestedEvent`, cancellable)**
   - Runs on the asyncio thread while `App` is still `RUNNING`; **every window,
     WebView, tray and menu is fully alive**.
   - A handler can `await win.eval_js(...)` to save unsaved data, or even create a
     temporary window.
   - Calling `event.prevent()` cancels this exit and the app keeps running normally;
     a later `app.exit()` starts a fresh round of negotiation.
   - *Note*: pressing `Ctrl+C` again during the close negotiation forces the exit; if
     the process is destroyed by the OS directly, it goes straight to the second
     phase.

2. **Teardown and completion phase (`AppEvent.ClosedEvent`, irreversible)**
   - The native event loop returns, `app.state` switches to `STOPPED` atomically, and
     every pending `call_on_main` request settles with `AppClosedError`.
   - Native resources are released in order: all windows close first (each dispatching
     its own `WindowEvent.ClosedEvent`), then tray icons and menus are released.
   - `AppEvent.ClosedEvent(exit_code=...)` is dispatched (no new native calls should
     be started at this point).
   - After the close handlers have finished, the remaining async tasks are canceled
     (so coroutine `finally` blocks still run), async generators are shut down and the
     thread pool is closed.

```python
from lumiview import App, AppEvent

app = App(name="LifecycleDemo")


@app.on(AppEvent.ReadyEvent)
async def on_ready(event: AppEvent.ReadyEvent):
    # `main` from app.run(main) starts only after every ReadyEvent handler has finished
    print("App is ready")


@app.on(AppEvent.CloseRequestedEvent)
async def on_close_requested(event: AppEvent.CloseRequestedEvent):
    # Windows and the API are still usable here
    for win in app.windows:
        dirty = await win.eval_js("window.__hasUnsavedChanges")
        if dirty == "true":
            event.prevent()  # cancel this close
            return


@app.on(AppEvent.ClosedEvent)
async def on_closed(event: AppEvent.ClosedEvent):
    print(f"App fully exited, exit code: {event.exit_code}")
```

> **On `entry` exceptions**: if `main` in `app.run(main)` raises an uncaught exception,
> the framework logs the error and calls `app.exit(1)` automatically, so `app.run()`
> returns `1`.

---

## Event subscription, filtering and cancellation

`app.on(...)` and `win.on(...)` support both the **decorator form** and **passing the
handler directly**, and return a `Subscription` you can cancel at any time:

```python
from lumiview import WindowEvent

# 1. decorator form + a synchronous where= filter predicate
@win.on(WindowEvent.JsEvent, where=lambda e: e.event == "user.login")
async def on_login(event: WindowEvent.JsEvent):
    print("user login:", event.payload)


# 2. imperative registration + keep the Subscription for later cancellation
sub = win.on(WindowEvent.TitleChangedEvent, lambda e: print("new title:", e.title))
# when you no longer want the listener:
sub.cancel()  # idempotent; safe to call repeatedly
```

- `handler` is either a `def` (runs on the thread pool) or an `async def` (runs on the
  asyncio thread).
- `where=` runs synchronously and inline during dispatch, so it **must be a plain
  synchronous function**. If `where` itself raises, the exception is logged and the
  event is treated as a non-match.

---

## One-shot waits: `wait_for()` and `wait_loaded()`

When you only need to wait in a coroutine for the next occurrence of an event, there
is no need to build an `asyncio.Event` by hand:

```python
# wait for the window to finish loading (recommended: Window.create() pre-registers
# it, so there is no race)
await win.wait_loaded(timeout=10)

# register a one-shot waiter (always before the action that triggers the event)
waiter = win.wait_for(
    WindowEvent.TitleChangedEvent,
    where=lambda e: "done" in e.title,
    timeout=5.0,
)
await win.eval_js("document.title = 'Task done'")
event = await waiter
print(event.title)
```

- If the window or app closes before the event arrives, a pending `wait_for` fails
  immediately with `WindowClosedError` or `AppClosedError` — it never hangs
  indefinitely.
- On timeout it raises `TimeoutError`.

---

## Event class hierarchy and preventable events

Every event derives from `Event`; only events that genuinely support canceling their
default behavior derive from `WindowPreventableEvent` or `AppPreventableEvent` (which
carry `.prevent()` and `.prevented`):

### `AppEvent` at a glance

| Event class | Preventable | Key fields and notes |
|---|---|---|
| `AppEvent.ReadyEvent` | ❌ | The app is ready; dispatched before `entry` and awaited to completion |
| `AppEvent.CloseRequestedEvent` | ✅ | Exit negotiation, `exit_code: int` |
| `AppEvent.ClosedEvent` | ❌ | Fires after the app is fully closed, `exit_code: int` |
| `AppEvent.ReopenEvent` | ❌ | Fires on a Dock icon click on macOS, `has_visible_windows: bool` |
| `AppEvent.OpenedEvent` | ❌ | The app was launched through a custom URL scheme / file association, `urls: list[str]` |
| `AppEvent.MenuItemActivatedEvent` | ❌ | Menu item activation, `id: str`, `menu_item` |
| `AppEvent.TrayIconClickEvent` etc. | ❌ | Tray click/double-click/enter/move/leave, with `id`, `position`, `rect`, `tray` |
| `AppEvent.Device*Event` | ❌ | Global device events (connect/disconnect/mouse/wheel/key/text) |

### `WindowEvent` at a glance

| Category | Event class | Preventable | Key fields and notes |
|---|---|---|---|
| **Page** | `PageLoadStartedEvent` / `PageLoadFinishedEvent` | ❌ | `url: str` |
| | `TitleChangedEvent` | ❌ | `title: str` |
| **Interception** | `NavigationRequestedEvent` | ✅ | `url: str`; `prevent()` blocks the navigation |
| | `NewWindowRequestedEvent` | ✅ | `url: str` (embedded new windows are denied by default and opened in the system browser; `prevent()` blocks it entirely; `open_in(url)` changes the external URL) |
| | `DownloadStartedEvent` | ✅ | `url: str`, `suggested_path: str`; `prevent()` cancels the download, or `save_to(path)` redirects the save path |
| | `DownloadCompletedEvent` | ❌ | `url: str`, `saved_path: str \| None`, `success: bool` |
| **Window** | `CloseRequestedEvent` | ✅ | `prevent()` cancels this close; otherwise `close_behavior` applies |
| | `ClosedEvent` | ❌ | The window and WebView have been destroyed (fires once) |
| | `ResizedEvent` / `MovedEvent` | ❌ | Physical pixels `width`, `height` / `x`, `y` |
| | `FocusedEvent` / `UnfocusedEvent` | ❌ | The window gained/lost focus |
| | `ScaleFactorChangedEvent` | ❌ | `scale_factor: float` |
| | `ThemeChangedEvent` | ❌ | `theme: Theme` (`Light` / `Dark`) |
| | `StartedEvent` / `SuspendedEvent` / `ResumedEvent` / `StoppedEvent` / `DecorationsClickEvent` | ❌ | Window state and decoration double-click lifecycle |
| **Drag and input** | `DragEvent` | ❌ | File drop, `kind: DragDropEvent`, `paths`, `position` (**requires `WindowOptions(drag_drop=True)`**) |
| | `ReceivedImeTextEvent` | ❌ | IME composition text `text: str` |
| | `TouchpadPressureEvent` / `AxisMotionEvent` / `TouchEvent` | ❌ | Touchpad pressure, joystick axes and touch events |
| **IPC** | `JsEvent` | ❌ | Emitted by the page through `__LUMIVIEW__.emit()`, `event: str`, `payload` |
| | `WebMessageReceivedEvent` | ❌ | Every raw message string from `window.ipc.postMessage`, `message: str` |

### Built-in navigation policy: `utils.navigation_policy`

To quickly restrict the WebView to specific domains (`*` wildcards, with `deny`
taking precedence over `allow`):

```python
from lumiview import WindowEvent, utils

win.on(
    WindowEvent.NavigationRequestedEvent,
    utils.navigation_policy(
        allow=("lumiview://*", "https://example.com/*"),
        deny=("https://example.com/admin/*",),
    ),
)
```

> **Tip**: for early events such as `PageLoadStartedEvent` that can fire as soon as
> the window is created, subscribe through the `WindowOptions(prepare=...)` hook
> before the native window is instantiated.
