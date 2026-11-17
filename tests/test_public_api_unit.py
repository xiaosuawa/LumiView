"""Public surface: Subscription registration, window identity, JS evaluation, menu views."""

from __future__ import annotations

import asyncio
import threading

from lumiview import (
    App,
    AppState,
    Subscription,
    Window,
    WindowClosedError,
)
from lumiview.events import WindowEvent
from lumiview.menu import Menu, MenuItem


def test_app_state_has_no_exit_phase():
    """A pending exit is a flag, not a phase: the app keeps running."""
    assert [state.name for state in AppState] == ["CREATED", "RUNNING", "STOPPED"]


def test_is_running_and_is_stopped_follow_the_state():
    """The two booleans are pure sugar over the monotonic phase."""
    app = object.__new__(App)
    for state, running, exited in (
        (AppState.CREATED, False, False),
        (AppState.RUNNING, True, False),
        (AppState.STOPPED, False, True),
    ):
        app._state = state
        assert app.is_running is running, state
        assert app.is_stopped is exited, state


def test_a_committed_exit_keeps_the_request_latched():
    """Only ``prevent()`` releases the latch — a commit must leave it set."""
    app = object.__new__(App)
    app._name = "test"
    app._state = AppState.RUNNING
    app._exit_code = 0
    app._exit_requested = threading.Event()
    app._handlers = {}
    app._handlers_lock = threading.Lock()
    app._async_loop = None
    app._proxy = None

    asyncio.run(app._negotiate_exit(3))

    assert app._exit_requested.is_set()
    assert app._exit_code == 3

    # First request wins: a later one is ignored without touching the code.
    app.exit(9)
    assert app._exit_code == 3


def test_exit_without_a_loop_still_records_the_code():
    """The no-asyncio fallback must latch the request and keep the exit code."""
    app = object.__new__(App)
    app._name = "test"
    app._state = AppState.RUNNING
    app._exit_code = 0
    app._exit_requested = threading.Event()
    app._async_loop = None
    app._proxy = None

    app.exit(3)

    assert app._exit_requested.is_set()
    assert app._exit_code == 3

    # A later request is ignored; a stopped app ignores it entirely.
    app._state = AppState.STOPPED
    app.exit(9)
    assert app._exit_code == 3


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


def test_on_registers_a_handler_without_calling_the_subscription():
    """``on(event, handler)`` is the imperative form; the decorator form stays."""
    window = object.__new__(Window)
    window._handlers = {}
    window._handlers_lock = threading.Lock()
    window._drag_enabled = False

    handler = lambda event: None
    where = lambda event: True

    sub = window.on(WindowEvent.TitleChangedEvent, handler, where=where)

    assert window._handlers[WindowEvent.TitleChangedEvent] == [(handler, where)]

    sub.cancel()
    assert window._handlers[WindowEvent.TitleChangedEvent] == []


def test_eval_js_fails_without_subscribing_when_the_window_is_closed():
    window = object.__new__(Window)
    window._win_id = 7
    window._closed = True
    window._handlers = {}
    window._handlers_lock = threading.Lock()
    window._drag_enabled = False

    handle = window.eval_js("1 + 1")

    assert handle.done()
    assert isinstance(handle.exception(), WindowClosedError)
    # A closed window cannot emit ClosedEvent again: no handler is left behind.
    assert window._handlers == {}


def test_eval_js_drops_the_close_watcher_once_the_task_settles(monkeypatch):
    """The WebView may vanish before the page answers — the watcher is the fallback."""
    from lumiview.app import App as AppClass

    app = object.__new__(AppClass)
    app._state = AppState.RUNNING
    app._main_tid = threading.get_ident()
    monkeypatch.setattr(AppClass, "_instance", app)

    window = object.__new__(Window)
    window._win_id = 7
    window._closed = False
    window._webview = None
    window._handlers = {}
    window._handlers_lock = threading.Lock()
    window._drag_enabled = False

    handle = window.eval_js("1 + 1")

    assert isinstance(handle.exception(), WindowClosedError)
    assert window._handlers[WindowEvent.ClosedEvent] == []
