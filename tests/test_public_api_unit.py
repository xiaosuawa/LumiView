"""Public read-only surface: Subscription, window identity, menu views."""

from __future__ import annotations

import threading

from lumiview import App, Subscription, Window
from lumiview.events import WindowEvent
from lumiview.menu import Menu, MenuItem


def test_subscription_cancel_unregisters():
    handlers: dict = {}
    sub = Subscription(handlers, WindowEvent.TitleChangedEvent, None, threading.Lock())

    @sub
    def handler(event):
        return None

    assert len(handlers[WindowEvent.TitleChangedEvent]) == 1

    sub.cancel()
    assert handlers[WindowEvent.TitleChangedEvent] == []

    sub.cancel()  # idempotent


def test_window_identity_is_read_only():
    window = object.__new__(Window)
    window._win_id = 7
    window._closed = False
    window._bridge = None

    assert window.id == 7
    assert window.is_closed is False
    assert window.bridge is None

    try:
        window.bridge = object()  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("Window.bridge must be read-only")


def test_menu_items_view_and_item_copy():
    menu = Menu.default_app_menu()
    assert isinstance(menu.items, tuple)
    assert len(menu.items) == 3

    item = MenuItem(text="a", on_activate=lambda event: None)
    clone = item.copy(text="b", enabled=False)
    assert clone.text == "b"
    assert clone.enabled is False
    # copy() keeps id and handlers; dataclasses.replace() does not.
    assert clone.id == item.id
    assert clone._activate_callbacks == item._activate_callbacks


def test_app_window_snapshot_and_lookup():
    app = object.__new__(App)
    app._windows = {7: "window"}
    app._windows_lock = threading.Lock()

    assert app.windows == ("window",)
    assert app.get_window(7) == "window"
    assert app.get_window(8) is None
