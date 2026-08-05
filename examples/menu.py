"""
menu.py — Native menus (muda).

Demonstrates the menu API:

- :class:`MenuItem` with accelerators and per-item ``on_activate``
  callbacks plus the global ``AppEvent.MenuItemActivatedEvent`` channel.
- Windows: ``await menu.attach_to_window(win)`` attaches the menu as the
  window's menu bar (below the title bar).
- macOS: the default Application/Edit/Window menu bar is installed
  automatically by ``App.run()``; this example replaces it with a custom
  menu via ``await menu.install_nsapp()``.

Handlers may be sync or async (auto-detected): async handlers are awaited
on the asyncio loop, sync handlers run on the app's thread pool — never
on the GUI thread. Equivalent forms: pass ``on_activate=fn`` at
construction, or register later via ``item.on_activate(fn)`` (decorator).

Note: on Windows the accelerator is shown in the menu but is not
triggered by the keyboard (the tao message loop does not translate
accelerators).

Run:
    python examples/menu.py
"""

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

# Handlers receive the MenuItemActivatedEvent (id + the item wrapper).


async def on_open(event: AppEvent.MenuItemActivatedEvent):
    print(f"Open activated (id={event.id!r})")


def on_mute(_):
    # Read the state from the item we hold, not from event.menu_item:
    # the data carrier mirrors the native check state (dual-write model),
    # and its type is precise (CheckMenuItem.checked) where the event's
    # menu_item field is a union (MenuItem | Submenu | None).
    print(f"Mute toggled to {mute_item.checked}")


def on_quit(_):
    print("Quit activated")
    app.exit()


# Menu items are pure data — construct them before App.run() on any
# thread, passing the handler straight into the constructor.
mute_item = CheckMenuItem(text="Mute", accelerator="CmdOrCtrl+M", id="mute")

file_menu = Submenu(
    text="File",
    items=[
        MenuItem(
            text="Open…", accelerator="CmdOrCtrl+O", id="open",
            on_activate=on_open,  # async handler — awaited on the asyncio loop
        ),
        mute_item,
        PredefinedMenuItem.separator(),
        MenuItem(text="Quit", id="quit", on_activate=on_quit),
    ],
)

# Equivalent alternative: register after construction, decorator style.
# @file_menu.items[0].on_activate
# def on_open(event: AppEvent.MenuItemActivatedEvent):
#     print(f"Open activated (id={event.id!r})")


async def main():
    win = await Window.create(WindowOptions(title="Menu Demo"))

    # Global channel — fires for every item, after the item's own
    # callbacks. The event carries the id and the resolved wrapper.
    @app.on(AppEvent.MenuItemActivatedEvent)
    def on_any_menu(event: AppEvent.MenuItemActivatedEvent):
        print(f"global: id={event.id!r} item={event.menu_item!r}")

    menu = await Menu.create(items=[file_menu])

    if sys.platform == "win32":
        await menu.attach_to_window(win)
        print("Menu attached to window — click File/Open… in the menu bar.")
    elif sys.platform == "darwin":
        # macOS already installed the default menu; replace it.
        await menu.install_nsapp()
        print("Custom menu installed — press Cmd+O to trigger Open….")

    print("App running — close the window or press Ctrl+C to exit.")


if __name__ == "__main__":
    app.run(main)
