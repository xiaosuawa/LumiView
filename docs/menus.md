# Menus and Tray Icons

Menu items are plain data objects: you build them anywhere (even before `App.run`),
and they are materialized on the GUI thread when a menu is attached to a window, the
macOS app menu, or a tray icon.

```python
from lumiview import AppEvent, CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu

mute = CheckMenuItem(text="Mute", accelerator="CmdOrCtrl+M", id="mute")


def on_open(event: AppEvent.MenuItemActivatedEvent) -> None:
    print("open", event.id)


file_menu = Submenu(
    text="File",
    items=[
        MenuItem(text="Open…", accelerator="CmdOrCtrl+O", id="open", on_activate=on_open),
        mute,
        PredefinedMenuItem.separator(),
        MenuItem(text="Quit", id="quit", on_activate=lambda _: app.exit()),
    ],
)

menu = await Menu.create(items=[file_menu])
```

- Item ids are strings and are echoed back on activation. Omit `id=` to get an
  auto-generated one.
- `accelerator` uses muda syntax: `Ctrl`, `Shift`, `Alt`, `Cmd`, `CmdOrCtrl`,
  e.g. `"CmdOrCtrl+Shift+K"`.
- `PredefinedMenuItem` covers system items (`separator()`, `copy()`, `cut()`,
  `paste()`, `undo()`, `quit()`, `about()`, ...). They perform their native action
  and do not emit activation events.
- Handlers are sync or `async`; they run off the GUI thread. Register at construction
  (`on_activate=fn`) or later with the decorator form `@item.on_activate`.

## Attaching

```python
# Windows: menu bar of a window
await menu.attach_to_window(win)
await menu.remove_from_window(win)

# macOS: application menu bar
await menu.install_nsapp()
await menu.remove_from_nsapp()
```

`attach_to_window` is Windows-only and `install_nsapp` is macOS-only — each raises
`NotImplementedError` on other platforms. LumiView installs a default macOS app menu
(Application / Edit / Window) from `App.run()`, so a custom menu simply replaces it.
There is no window menu bar on Linux.

Two activation channels fire in order:

1. the item's own `on_activate` handler (leaf items only);
2. the global `AppEvent.MenuItemActivatedEvent` (for `app.on(...)`), whose
   `menu_item` field is the matching wrapper.

## Updating items at runtime

State lives in the Python wrapper and is mirrored to the native item once it has
been materialized (dual-write):

```python
await item.set_text("Save as…")
await item.set_enabled(False)
await check_item.set_checked(True)
await item.set_accelerator("CmdOrCtrl+Shift+S")
```

Use the wrapper as the source of truth (`check_item.checked`), not
`event.menu_item`, whose type is a union.

## Reading and copying items

`Menu.items` is a read-only snapshot (`tuple[Item, ...]`). To derive a variant of
an existing item, use `MenuItem.copy(**changes)` / `Submenu.copy(**changes)`
instead of `dataclasses.replace`:

```python
save_as = file_menu.items[0].copy(text="Save As…", id="save-as")
```

`copy()` keeps the `id` and the registered `on_activate` handlers — both are
`init=False` fields, so `dataclasses.replace` would regenerate the id and silently
drop activation routing. Unknown field names raise `TypeError`.

## Tray icons

```python
from lumiview import Menu, MenuItem, PredefinedMenuItem, TrayIcon, TrayIconOptions

menu = await Menu.create(items=[MenuItem(text="Show", id="show"), PredefinedMenuItem.separator(), MenuItem(text="Quit", id="quit")])

tray = await TrayIcon.create(
    TrayIconOptions(
        icon=(rgba_bytes, 32, 32),      # raw RGBA, a file path, or a PIL image
        tooltip="My App",
        menu=menu,
        menu_on_left_click=False,
    )
)

await tray.set_tooltip("Busy")
await tray.set_visible(False)
await tray.close()                      # or just drop the wrapper
```

`TrayIconOptions` fields: `icon`, `id`, `tooltip`, `menu`, `menu_on_left_click`,
`menu_on_right_click`, `icon_as_template` (macOS template image).

## Tray events

```python
from lumiview import AppEvent, ElementState, MouseButton

@app.on(AppEvent.TrayIconClickEvent)
async def on_click(event):
    if event.button == MouseButton.Left and event.button_state == ElementState.Released:
        await win.toggle_visibility()
```

`TrayIconClickEvent` carries `id`, `position`, `rect`, `button`, `button_state` and
`tray`. There are also `TrayIconDoubleClickEvent` (Windows only), `TrayIconEnterEvent`,
`TrayIconMoveEvent` and `TrayIconLeaveEvent`, all emitted globally.

## Close-to-tray

```python
app = App(name="TrayApp", exit_on_last_window=False)

@win.on(WindowEvent.CloseRequestedEvent)
async def on_close_requested(event):
    event.prevent()
    await app.hide()
```

With `exit_on_last_window=False` the app keeps running after the window is hidden;
restore it from a tray click or menu item. On macOS `AppEvent.ReopenEvent` fires on
Dock clicks.

## Platform notes

- **Windows:** menu accelerators are displayed but do not fire while the WebView2
  content has keyboard focus (the message loop never sees the key). Use the JS
  `keydown` + IPC path if you need working shortcuts there.
- **macOS:** the app menu bar exists whether or not windows are open; `App.hide()`
  animates windows into the Dock.
- **Linux:** no window menu bar; tray tooltips are unsupported; a tray menu cannot be
  replaced after creation.
- Menu and tray wrappers are kept alive by the app; a dropped `TrayIcon` removes the
  icon.
