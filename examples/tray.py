"""
tray.py — Close-to-tray pattern, cross-platform.

- Left-click the tray icon toggles the window (``menu_on_left_click=False``);
  right-click opens the menu.
- Closing the window intercepts :class:`WindowEvent.CloseRequestedEvent`:
  the close is prevented and the whole app is hidden via :meth:`App.hide` —
  the same code path on every platform. On macOS the windows genie into
  the Dock and a Dock click reopens the app (``AppEvent.ReopenEvent``);
  on other platforms the windows are simply hidden (restore from the tray
  menu or a left click).
- macOS: the default menu bar from :meth:`App.run` gives Cmd+Q / Cmd+W
  out of the box.

Run:
    python examples/tray.py
"""

from lumiview import (
    App,
    AppEvent,
    CloseBehavior,
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


def make_icon() -> bytes:
    """32x32 RGBA icon: a blue circle on transparent."""
    size, cx, cy, r = 32, 15.5, 15.5, 13
    rgba = bytearray()
    for y in range(size):
        for x in range(size):
            rgba += (
                bytes((66, 133, 244, 255))
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r
                else bytes((0, 0, 0, 0))
            )
    return bytes(rgba)


win: Window | None = None


async def toggle_window():
    if win is None:
        return
    await win.toggle_visibility()
    if await win.is_visible():
        await win.focus()
    print(f"Window {'hidden' if not await win.is_visible() else 'shown'} (tray click)")


# Tray menu — same MenuItem type as menu bars.

show_item = MenuItem(text="Show Window", id="show")
close_item = MenuItem(text="Close Window", id="close")
quit_item = MenuItem(text="Quit", id="quit")


@show_item.on_activate
async def on_show(_):
    if win is None:
        return
    await win.show()
    await win.focus()
    print("Window shown from tray menu")


@close_item.on_activate
async def on_close(_):
    if win is None:
        return
    await win.request_close()
    print("Close requested from tray menu")


@quit_item.on_activate
async def on_quit(_):
    print("Quit from tray menu")
    app.exit()


async def main():
    global win

    win = await Window.create(
        WindowOptions(
            title="Tray Demo",
            close_behavior=CloseBehavior.Close,
            html="<h1>LumiView Tray Demo</h1><p>Close the window to hide it to the tray.</p>",
        )
    )

    @win.on(WindowEvent.CloseRequestedEvent)
    async def on_close_requested(event):
        event.prevent()
        await app.hide()
        print("App hidden")

    # macOS: reopen from the Dock.
    @app.on(AppEvent.ReopenEvent)
    async def on_reopen(event: AppEvent.ReopenEvent):
        # Fires on any Dock click (visible or not). When windows are
        # still visible the system already re-activated the app — only
        # restore when they are hidden (e.g. after App.hide()).
        if win is None or event.has_visible_windows:
            return
        await win.show()
        await win.focus()
        print("App reopened from the Dock")

    @app.on(AppEvent.TrayIconClickEvent)
    async def on_tray_click(event: AppEvent.TrayIconClickEvent):
        if event.button == MouseButton.Left and event.button_state == ElementState.Released:
            await toggle_window()

    # Global channel — fires after each item's own on_activate.
    @app.on(AppEvent.MenuItemActivatedEvent)
    async def on_any_menu(event: AppEvent.MenuItemActivatedEvent):
        print(f"global menu event: id={event.id!r}")

    menu = await Menu.create(
        items=[show_item, close_item, PredefinedMenuItem.separator(), quit_item]
    )
    tray = await TrayIcon.create(
        TrayIconOptions(
            icon=(make_icon(), 32, 32),
            tooltip="LumiView Tray Demo",
            menu=menu,
            menu_on_left_click=False,
        )
    )
    print(f"Tray icon created (id={tray.id})")
    print("Left-click the tray icon to toggle the window; right-click for the menu.")


if __name__ == "__main__":
    app.run(main)
