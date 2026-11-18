"""Event class system.

:class:`WindowBaseEvent` / :class:`AppBaseEvent` carry the context shared by a
whole event family. Only the events whose default behavior can be cancelled
derive from :class:`WindowPreventableEvent` / :class:`AppPreventableEvent`,
which add ``prevented`` and :meth:`~WindowPreventableEvent.prevent` — the other
events have no ``prevent()`` at all. :class:`WindowEvent` and :class:`AppEvent`
are namespace containers. Every event is a slots dataclass, so type checkers
see the full shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

# Re-exported so ``WindowEvent.DragEvent.kind`` can be compared without
# importing wryview directly (see ``lumiview.DragDropEvent``).
from wryview import DragDropEvent

if TYPE_CHECKING:
    from lumiview.window import Window
    from lumiview._core import (
        ElementState,
        MouseButton,
        ScrollDeltaKind,
        Theme,
        TouchPhase,
    )
    from lumiview.menu import MenuItem, Submenu
    from lumiview.tray import TrayIcon


class Event:
    """Common ancestor of all lumiview events (empty)."""

    __slots__ = ()


@dataclass(slots=True, kw_only=True)
class WindowBaseEvent(Event):
    """Base of all window events: the window the event belongs to.

    ``window`` is filled in by the dispatcher before handlers run.
    """

    window: Window | None = None


@dataclass(slots=True, kw_only=True)
class WindowPreventableEvent(WindowBaseEvent):
    """Base of the window events whose default behavior can be cancelled.

    A handler calls :meth:`prevent` to keep the current behavior — stay on the
    page, block the download, keep the window open. These events are dispatched
    from synchronous native callbacks, which block until every handler finished,
    so their handlers must not block on the GUI thread.
    """

    prevented: bool = False

    def prevent(self) -> None:
        """Cancel the default behavior of this event."""
        self.prevented = True


class AppBaseEvent(Event):
    """Base class of all app events."""

    __slots__ = ()


@dataclass(slots=True, kw_only=True)
class AppPreventableEvent(AppBaseEvent):
    """Base of the app events whose default behavior can be cancelled.

    A handler calls :meth:`prevent` to cancel the action (for example to keep the
    app running after a close request).
    """

    prevented: bool = False

    def prevent(self) -> None:
        """Cancel the default behavior of this event."""
        self.prevented = True


class WindowEvent:
    """Window event namespace (pure module separation)."""

    # Page

    @dataclass(slots=True, kw_only=True)
    class PageLoadStartedEvent(WindowBaseEvent):
        """A page load has started (initial page or a navigation)."""

        url: str

    @dataclass(slots=True, kw_only=True)
    class PageLoadFinishedEvent(WindowBaseEvent):
        """A page load has finished."""

        url: str

    @dataclass(slots=True, kw_only=True)
    class TitleChangedEvent(WindowBaseEvent):
        """The page title changed."""

        title: str

    # Navigation / new window (preventable + extension actions)

    @dataclass(slots=True, kw_only=True)
    class NavigationRequestedEvent(WindowPreventableEvent):
        """A navigation is requested; prevent it to stay on the current page."""

        url: str

    @dataclass(slots=True, kw_only=True)
    class NewWindowRequestedEvent(WindowPreventableEvent):
        """The page requested a new window (e.g. ``window.open``).

        Denied by default — the URL opens in the system browser. Prevent to block it
        entirely, or call :meth:`open_in` to override the target.
        """

        url: str
        _open_url: str | None = None

        def open_in(self, url: str) -> None:
            """Open *url* in the system browser (the in-webview window is denied)."""
            self._open_url = url

    # Drag & drop

    @dataclass(slots=True, kw_only=True)
    class DragEvent(WindowBaseEvent):
        """File drag & drop over the window.

        Only emitted after a handler is registered for this class: the wryview handler
        is installed lazily so WebView2's built-in external-file drops keep working.
        """

        kind: DragDropEvent
        paths: list[str]
        position: tuple[int, int]

    # Downloads

    @dataclass(slots=True, kw_only=True)
    class DownloadStartedEvent(WindowPreventableEvent):
        """A download is about to start.

        Prevent to cancel it, or redirect with :meth:`save_to` (default: the suggested
        path).
        """

        url: str
        suggested_path: str
        _save_path: str | None = None

        def save_to(self, path: str) -> None:
            """Redirect the download to *path* instead of the suggested one."""
            self._save_path = path

    @dataclass(slots=True, kw_only=True)
    class DownloadCompletedEvent(WindowBaseEvent):
        """A download finished, successfully or not."""

        url: str
        saved_path: str | None
        success: bool

    # Window (tao events)

    class CloseRequestedEvent(WindowPreventableEvent):
        """The window received a close request; prevent to cancel it.

        Otherwise ``close_behavior`` is applied.
        """

        ...

    class ClosedEvent(WindowBaseEvent):
        """The window and its WebView are gone (dispatched once)."""

        ...

    @dataclass(slots=True, kw_only=True)
    class ResizedEvent(WindowBaseEvent):
        """The window was resized (physical pixels)."""

        width: int
        height: int

    @dataclass(slots=True, kw_only=True)
    class MovedEvent(WindowBaseEvent):
        """The window moved (physical screen coordinates)."""

        x: int
        y: int

    class FocusedEvent(WindowBaseEvent):
        """The window gained focus."""

        ...

    class UnfocusedEvent(WindowBaseEvent):
        """The window lost focus."""

        ...

    @dataclass(slots=True, kw_only=True)
    class ScaleFactorChangedEvent(WindowBaseEvent):
        """The display scale factor changed (e.g. across monitors)."""

        scale_factor: float

    @dataclass(slots=True, kw_only=True)
    class ThemeChangedEvent(WindowBaseEvent):
        """The system or window theme changed."""

        theme: Theme

    # Window lifecycle (tao)

    class StartedEvent(WindowBaseEvent):
        """The window started (became active)."""

        ...

    class SuspendedEvent(WindowBaseEvent):
        """The window was suspended."""

        ...

    class ResumedEvent(WindowBaseEvent):
        """The window resumed from suspension."""

        ...

    class StoppedEvent(WindowBaseEvent):
        """The window stopped."""

        ...

    class DecorationsClickEvent(WindowBaseEvent):
        """The user double-clicked the window decorations (Windows)."""

        ...

    # Input (extended)

    @dataclass(slots=True, kw_only=True)
    class ReceivedImeTextEvent(WindowBaseEvent):
        """IME pre-edit / committed text (e.g. pinyin candidates)."""

        text: str

    @dataclass(slots=True, kw_only=True)
    class TouchpadPressureEvent(WindowBaseEvent):
        """Touchpad pressure changed (macOS)."""

        pressure: float
        stage: int

    @dataclass(slots=True, kw_only=True)
    class AxisMotionEvent(WindowBaseEvent):
        """Joystick / additional input axis motion."""

        axis: int
        value: float

    @dataclass(slots=True, kw_only=True)
    class TouchEvent(WindowBaseEvent):
        """A touch contact on a touch screen."""

        phase: TouchPhase
        x: float
        y: float
        force: float | None
        id: int

    # IPC

    @dataclass(slots=True, kw_only=True)
    class JsEvent(WindowBaseEvent):
        """A fire-and-forget event emitted by the page (``__LUMIVIEW__.emit``).

        Use a :class:`~lumiview.bridge.Bridge` command for request/response.
        """

        event: str
        payload: Any = None

    @dataclass(slots=True, kw_only=True)
    class WebMessageReceivedEvent(WindowBaseEvent):
        """A raw message from the page's ``window.ipc.postMessage``.

        Emitted for every IPC message, even when a ``Bridge`` handles it. In
        ``untrusted`` mode this is the only way to receive page messages.
        """

        message: str


class AppEvent:
    """App event namespace (pure module separation)."""

    class ReadyEvent(AppBaseEvent):
        """The app is ready — dispatched once, right before ``entry`` runs.

        Every handler finishes before ``entry`` starts; a failing handler is logged
        and the remaining ones still run, so it never aborts the startup.
        """

        ...

    @dataclass(slots=True, kw_only=True)
    class CloseRequestedEvent(AppPreventableEvent):
        """A graceful exit was requested — the cancellable close hook.

        Dispatched before anything is torn down: windows, menus and trays are alive and
        the whole API keeps working, so a handler may save state or ask the user. There
        is no timeout. Call :meth:`prevent` to cancel the exit; a later ``exit()``
        starts over.

        Only negotiated exits dispatch it (``exit()``, the last-window policy, a failing
        ``entry``/Ready handler) — a process that terminates on its own (macOS
        ``LoopDestroyed``) only dispatches :class:`ClosedEvent`.
        """

        exit_code: int = 0

    @dataclass(slots=True, kw_only=True)
    class ClosedEvent(AppBaseEvent):
        """The app has closed — the irreversible cleanup notification.

        Dispatched exactly once, after the native loop returned and every window, tray
        and menu was released. New work fails with ``AppClosedError``; outstanding
        :meth:`App.wait_for` waiters fail too. Carries the value :meth:`App.run`
        returns.
        """

        exit_code: int = 0

    @dataclass(slots=True, kw_only=True)
    class ReopenEvent(AppBaseEvent):
        """The app was reopened from the Dock icon (macOS)."""

        has_visible_windows: bool

    # Loop-level events (not tied to a window)

    @dataclass(slots=True, kw_only=True)
    class OpenedEvent(AppBaseEvent):
        """The app was opened with URLs (custom scheme / file association)."""

        urls: list[str]

    # Device events (global input devices)

    class DeviceAddedEvent(AppBaseEvent):
        """An input device was connected."""

        ...

    class DeviceRemovedEvent(AppBaseEvent):
        """An input device was disconnected."""

        ...

    @dataclass(slots=True, kw_only=True)
    class DeviceMouseMotionEvent(AppBaseEvent):
        """Global (device-level) pointer motion."""

        dx: float
        dy: float

    @dataclass(slots=True, kw_only=True)
    class DeviceMouseWheelEvent(AppBaseEvent):
        """Global (device-level) mouse wheel."""

        delta_kind: ScrollDeltaKind
        dx: float
        dy: float

    @dataclass(slots=True, kw_only=True)
    class DeviceMotionEvent(AppBaseEvent):
        """Global (device-level) axis motion."""

        axis: int
        value: float

    @dataclass(slots=True, kw_only=True)
    class DeviceButtonEvent(AppBaseEvent):
        """Global (device-level) mouse button."""

        button: int
        state: ElementState

    @dataclass(slots=True, kw_only=True)
    class DeviceKeyEvent(AppBaseEvent):
        """Global (device-level) keyboard event."""

        physical_key: str
        state: ElementState

    @dataclass(slots=True, kw_only=True)
    class DeviceTextEvent(AppBaseEvent):
        """Global (device-level) text input."""

        codepoint: int

    # Menu events

    @dataclass(slots=True, kw_only=True)
    class MenuItemActivatedEvent(AppBaseEvent):
        """A menu item was activated (app menu, window menu bar or tray menu).

        Predefined system items perform their OS action and never emit it. ``menu_item``
        is filled by the dispatcher (``None`` for an unknown id).
        """

        id: str
        menu_item: "MenuItem | Submenu | None" = None

    # Tray icon events

    @dataclass(slots=True, kw_only=True)
    class TrayIconClickEvent(AppBaseEvent):
        """A click on a tray icon (``tray`` is filled by the dispatcher)."""

        id: str
        position: tuple[float, float]
        rect: tuple[float, float, float, float]
        button: MouseButton
        button_state: ElementState
        tray: "TrayIcon | None" = None

    @dataclass(slots=True, kw_only=True)
    class TrayIconDoubleClickEvent(AppBaseEvent):
        """A double click on a tray icon (Windows only)."""

        id: str
        position: tuple[float, float]
        rect: tuple[float, float, float, float]
        button: MouseButton
        tray: "TrayIcon | None" = None

    @dataclass(slots=True, kw_only=True)
    class TrayIconEnterEvent(AppBaseEvent):
        """The pointer entered the tray icon region."""

        id: str
        position: tuple[float, float]
        rect: tuple[float, float, float, float]
        tray: "TrayIcon | None" = None

    @dataclass(slots=True, kw_only=True)
    class TrayIconMoveEvent(AppBaseEvent):
        """The pointer moved over the tray icon region."""

        id: str
        position: tuple[float, float]
        rect: tuple[float, float, float, float]
        tray: "TrayIcon | None" = None

    @dataclass(slots=True, kw_only=True)
    class TrayIconLeaveEvent(AppBaseEvent):
        """The pointer left the tray icon region."""

        id: str
        position: tuple[float, float]
        rect: tuple[float, float, float, float]
        tray: "TrayIcon | None" = None


__all__ = [
    "Event",
    "WindowBaseEvent",
    "WindowPreventableEvent",
    "AppBaseEvent",
    "AppPreventableEvent",
    "WindowEvent",
    "AppEvent",
    "DragDropEvent",
]
