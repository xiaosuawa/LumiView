# Native menus and system tray

LumiView integrates `muda` (native menus) and `tray-icon` (system tray). Menu items
and tray configuration are **pure data objects**: you can build them on any thread
before `App.run()`, and they are materialized on the main thread afterwards.

---

## Menu item types

| Class | Description | Key parameters |
|---|---|---|
| `MenuItem` | Regular clickable menu item | `text`, `id=None`, `enabled=True`, `accelerator=None`, `on_activate=None` |
| `CheckMenuItem` | Menu item with a checkbox | Inherits `MenuItem`; adds `checked=False` and `set_checked(bool)` |
| `Submenu` | Submenu / top-level menu bar category | `text`, `items=[]`, `id=None`, `enabled=True` |
| `PredefinedMenuItem` | Native system actions (copy / paste / separator / about, etc.) | Factory methods such as `.separator()`, `.copy()`, `.paste()`, `.about(name=..., version=...)` |

> **Note**: `PredefinedMenuItem` is performed natively by the operating system and
> does **not** trigger activation events on the Python side. To have a macOS Quit
> click go through `App`'s graceful shutdown, use a regular `MenuItem` bound to
> `app.exit()` (the menu bar installed by `App.run()` on macOS already handles this
> for you).

---

## Creation, runtime updates and event callbacks

### Dual-write model and thread safety

- **Property updates**: `item.set_text(...)`, `item.set_enabled(...)`,
  `item.set_accelerator(...)` and `check_item.set_checked(...)` are safe to call from
  any thread and return `Task[None]`.
- **Structural updates**: `menu.append/insert/remove` and
  `submenu.append/insert/remove` run serially on the main thread, so multi-threaded
  edits cannot make the data order diverge from the native menu.
- **Snapshots and copies**: `menu.items` returns a read-only `tuple` snapshot of the
  top-level items; to clone an existing item while keeping its original `id` and
  callbacks, use `item.copy(text="New name")` (not `dataclasses.replace`).

### Menu event example (Windows / macOS)

```python
import sys
from lumiview import (
    App,
    AppEvent,
    CheckMenuItem,
    Menu,
    MenuItem,
    PredefinedMenuItem,
    Submenu,
    Window,
    WindowOptions,
)

app = App(name="MenuDemo")

mute_item = CheckMenuItem(text="Mute", accelerator="CmdOrCtrl+M", id="mute")


@mute_item.on_activate
def on_mute(event: AppEvent.MenuItemActivatedEvent):
    print("current mute state:", mute_item.checked)


async def on_open(event: AppEvent.MenuItemActivatedEvent):
    print("open triggered:", event.id)


file_menu = Submenu(
    text="File",
    items=[
        MenuItem(text="Open…", accelerator="CmdOrCtrl+O", id="open", on_activate=on_open),
        mute_item,
        PredefinedMenuItem.separator(),
        MenuItem(text="Quit", id="quit", on_activate=lambda _: app.exit()),
    ],
)


async def main():
    win = await Window.create(WindowOptions(title="Menu Demo"))

    # You can also listen on the global menu activation channel (fires after the item's own on_activate)
    @app.on(AppEvent.MenuItemActivatedEvent)
    def on_any(event: AppEvent.MenuItemActivatedEvent):
        print(f"global menu event: id={event.id!r}")

    menu = await Menu.create(items=[file_menu])

    if sys.platform == "win32":
        await menu.attach_to_window(win)   # Windows: attach to the given window's menu bar
    elif sys.platform == "darwin":
        await menu.install_nsapp()         # macOS: replace the app's top-level application menu bar


app.run(main)
```

> **Platform note**: on Windows the accelerator text in the menu bar is display-only;
> the `tao` message loop does not forward accelerator presses by default. Listening
> for keyboard shortcuts in page JS and triggering the matching logic over the Bridge
> is the usual approach.

---

## System tray and close-to-tray

Combine `exit_on_last_window=False`, `WindowEvent.CloseRequestedEvent` and
`App.hide()` to get a cross-platform minimize-to-tray mode:

```python
from lumiview import (
    App,
    AppEvent,
    ElementState,
    Menu,
    MenuItem,
    MouseButton,
    PredefinedMenuItem,
    TrayIcon,
    TrayIconOptions,
    Window,
    WindowEvent,
    WindowOptions,
)

app = App(name="TrayDemo", exit_on_last_window=False)


def make_icon() -> tuple[bytes, int, int]:
    # Build a solid blue 32x32 RGBA icon (a file path or a PIL.Image.Image can be passed directly too)
    return bytes([66, 133, 244, 255] * (32 * 32)), 32, 32


async def main():
    win = await Window.create(WindowOptions(title="Tray Demo", html="<h1>Close hides to the tray</h1>"))

    async def restore():
        await win.show()
        await win.focus()

    # Don't destroy the window when close is clicked; hide the whole app instead
    @win.on(WindowEvent.CloseRequestedEvent)
    async def on_close(event):
        event.prevent()
        await app.hide()

    # macOS only: show hidden windows again when the Dock icon is clicked
    @app.on(AppEvent.ReopenEvent)
    async def on_reopen(event):
        if not event.has_visible_windows:
            await restore()

    # Toggle window visibility when the left mouse button is released on the tray icon
    @app.on(AppEvent.TrayIconClickEvent)
    async def on_tray_click(event):
        if event.button == MouseButton.Left and event.button_state == ElementState.Released:
            await win.toggle_visibility()

    tray_menu = await Menu.create(
        items=[
            MenuItem(text="Show window", on_activate=lambda _: restore()),
            PredefinedMenuItem.separator(),
            MenuItem(text="Quit completely", on_activate=lambda _: app.exit()),
        ]
    )

    tray = await TrayIcon.create(
        TrayIconOptions(
            icon=make_icon(),
            tooltip="LumiView tray example",
            menu=tray_menu,
            menu_on_left_click=False,   # left click toggles the window, right click opens the menu
            menu_on_right_click=True,
        )
    )


app.run(main)
```

### macOS menu-bar-only (agent) apps

To keep the app out of the macOS Dock and the `Cmd+Tab` switcher entirely, set
`ActivationPolicy.Accessory`:

```python
from lumiview import ActivationPolicy, App

app = App(
    name="MenuBarAgent",
    exit_on_last_window=False,
    activation_policy=ActivationPolicy.Accessory,  # only macOS accepts this
)
```

At runtime, `await app.set_dock_visibility(True/False)` toggles Dock icon visibility
dynamically.

> **Linux tray limits**: because of the underlying system tray protocol, `tooltip` is
> unsupported on Linux, and a tray menu cannot be replaced wholesale after creation
> (assemble the full menu up front when creating it).
