"""Type stubs for lumiview._core — tao window management binding."""

from enum import Enum
from typing import Callable

# ── Event Loop ─────────────────────────────────────────────────────────────

class EventLoopControl(Enum):
    """Return from an event callback to control the event loop."""

    Continue: EventLoopControl
    """Keep the event loop running (default)."""

    Exit: EventLoopControl
    """Stop the event loop cleanly."""

class TaoEventLoop:
    """Cross-platform event loop. Create exactly one per application.

    .. warning::
        **Not sendable** to other Python threads. Always create and run
        on the main thread, especially on macOS.
    """

    def __init__(self) -> None: ...
    def create_proxy(self) -> "TaoEventLoopProxy":
        """Create a thread-safe proxy for sending events from other threads.

        Must be called **before** :meth:`run`.
        """
        ...

    def run(self, callback: Callable[["TaoEvent"], EventLoopControl | None]) -> None:
        """Run the event loop. Blocks the calling thread until stopped.

        Calls ``callback(event)`` with a subclass of :class:`TaoEvent` for
        each interesting event. Use ``isinstance()`` to dispatch:

            def on_event(event):
                if isinstance(event, ResizedEvent):
                    print(event.width, event.height)
                elif isinstance(event, CloseRequestedEvent):
                    return EventLoopControl.Exit
                return EventLoopControl.Continue

        Return :class:`EventLoopControl.Exit` to stop the loop;
        ``None`` or ``Continue`` keeps it running.
        """
        ...

class TaoEventLoopProxy:
    """Thread-safe handle for sending user events into the event loop.

    Create via ``el.create_proxy()`` **before** calling ``el.run()``.
    Can be passed to ``threading.Thread`` targets.
    """

    def send_event(self, data: str) -> None:
        """Send a data string into the event loop from any thread.

        The event loop dispatches this as a :class:`UserEvent`.
        Raises ``RuntimeError`` if the loop has been closed.
        """
        ...

# ── Window ─────────────────────────────────────────────────────────────────

class TaoWindow:
    """A managed window.

    Construct directly with ``TaoWindow(event_loop, **options)`` — all
    options are keyword-only and ``None`` means "leave the platform
    default".

    .. warning::
        **Not sendable** to other Python threads — all window operations
        must happen on the main thread (the event loop thread).
    """

    def __init__(
        self,
        event_loop: "TaoEventLoop",
        *,
        title: str | None = None,
        width: float | None = None,
        height: float | None = None,
        min_size: tuple[float, float] | None = None,
        max_size: tuple[float, float] | None = None,
        position: tuple[float, float] | None = None,
        resizable: bool | None = None,
        minimizable: bool | None = None,
        maximizable: bool | None = None,
        closable: bool | None = None,
        maximized: bool | None = None,
        visible: bool | None = None,
        decorations: bool | None = None,
        undecorated_shadow: bool | None = None,
        always_on_top: bool | None = None,
        focused: bool | None = None,
        focusable: bool | None = None,
        content_protection: bool | None = None,
        visible_on_all_workspaces: bool | None = None,
        transparent: bool | None = None,
        icon: tuple[int, int, bytes] | None = None,  # (width, height, rgba)
    ) -> None: ...

    def id(self) -> int:
        """Return the unique integer identifier for this window.

        Use to match events to windows in multi-window apps:

            win1_id = win1.id()
            def on_event(event):
                if event.window_id == win1_id:
                    ...
        """
        ...

    def native_handle(self) -> int: ...
    def native_handle_kind(self) -> "WindowHandleKind": ...

    # Geometry
    def set_inner_size(self, width: float, height: float) -> None: ...
    def inner_size(self) -> tuple[float, float]: ...
    def outer_size(self) -> tuple[int, int]: ...
    def set_outer_position(self, x: float, y: float) -> None: ...
    def set_min_inner_size(self, width: float, height: float) -> None: ...
    def set_max_inner_size(self, width: float, height: float) -> None: ...

    # Appearance
    def set_title(self, title: str) -> None: ...
    def set_visible(self, visible: bool) -> None: ...
    def set_resizable(self, resizable: bool) -> None: ...
    def set_minimizable(self, minimizable: bool) -> None: ...
    def set_maximizable(self, maximizable: bool) -> None: ...
    def set_closable(self, closable: bool) -> None: ...
    def set_always_on_top(self, always: bool) -> None: ...
    def set_cursor_visible(self, visible: bool) -> None: ...
    def set_decorations(self, decorations: bool) -> None: ...
    def apply_effect(
        self,
        effect: "WindowEffect",
        color: tuple[int, int, int, int] | None = None,
    ) -> None: ...
    def clear_effect(self, effect: "WindowEffect") -> None: ...

    # State
    def is_minimized(self) -> bool: ...
    def is_maximized(self) -> bool: ...
    def is_visible(self) -> bool: ...
    def set_minimized(self, minimized: bool) -> None: ...
    def set_maximized(self, maximized: bool) -> None: ...
    def set_fullscreen(self, fullscreen: bool) -> None: ...

    # Icon
    def set_window_icon(self, width: int, height: int, rgba: bytes) -> None:
        """Set the window icon from raw RGBA pixel data."""
        ...
    # Focus
    def set_focused(self, focused: bool) -> None: ...

    # Interaction
    def drag_window(self) -> None: ...
    def drag_resize_window(self, direction: "ResizeDirection") -> None: ...
    def scale_factor(self) -> float: ...
    def request_redraw(self) -> None: ...
    def _redraw_transparent_surface(self) -> None: ...
    def gtk_container(self) -> int:
        """Return the raw pointer to the GTK container widget (Linux only).

        Pass to wryview with ``parent_hwnd_kind=WindowHandleKind.Gtk``
        for Wayland-compatible WebView embedding.
        Only exists on Linux — on Windows/macOS this method is absent
        (AttributeError).
        """
        ...

# ── Types ───────────────────────────────────────────────────────────────────

class WindowHandleKind(Enum):
    """Identifies the native window handle type."""

    Win32: WindowHandleKind
    AppKit: WindowHandleKind
    X11: WindowHandleKind
    Wayland: WindowHandleKind
    Gtk: WindowHandleKind

class WindowEffect(Enum):
    """Native background material applied to a window."""

    Blur: WindowEffect
    Acrylic: WindowEffect
    Mica: WindowEffect
    Vibrancy: WindowEffect

class ResizeDirection(Enum):
    """Edge or corner used for an interactive window resize."""

    East: ResizeDirection
    North: ResizeDirection
    NorthEast: ResizeDirection
    NorthWest: ResizeDirection
    South: ResizeDirection
    SouthEast: ResizeDirection
    SouthWest: ResizeDirection
    West: ResizeDirection

class EventKind(Enum):
    """Discriminant for :class:`TaoEvent`.

    Prefer ``isinstance()`` dispatch over matching on this enum directly —
    the event subclasses provide typed fields.
    """

    Resized: EventKind
    Moved: EventKind
    CloseRequested: EventKind
    Destroyed: EventKind
    Focused: EventKind
    Unfocused: EventKind
    Reopen: EventKind
    ScaleFactorChanged: EventKind
    ThemeChanged: EventKind
    MouseInput: EventKind
    CursorMoved: EventKind
    MouseWheel: EventKind
    KeyboardInput: EventKind
    ModifiersChanged: EventKind
    CursorEntered: EventKind
    CursorLeft: EventKind
    RedrawRequested: EventKind
    UserEvent: EventKind
    LoopDestroyed: EventKind

class MouseButton(Enum):
    """Mouse button identifier."""

    Left: MouseButton
    Right: MouseButton
    Middle: MouseButton
    Other: MouseButton

class ElementState(Enum):
    """Input element state."""

    Pressed: ElementState
    Released: ElementState

class ScrollDeltaKind(Enum):
    """Scroll delta unit."""

    Line: ScrollDeltaKind
    Pixel: ScrollDeltaKind

class TouchPhase(Enum):
    """Touch / scroll gesture phase."""

    Started: TouchPhase
    Moved: TouchPhase
    Ended: TouchPhase
    Cancelled: TouchPhase

class KeyLocation(Enum):
    """Physical key location."""

    Standard: KeyLocation
    Left: KeyLocation
    Right: KeyLocation
    Numpad: KeyLocation

class Theme(Enum):
    """System color theme."""

    Light: Theme
    Dark: Theme

class ModifiersState:
    """Keyboard modifier key state snapshot.

    Immutable — each event carries the modifier state at the moment it fired.
    """

    @property
    def shift(self) -> bool:
        """Shift key is held down."""
        ...

    @property
    def ctrl(self) -> bool:
        """Control key is held down."""
        ...

    @property
    def alt(self) -> bool:
        """Alt key is held down."""
        ...

    @property
    def super_key(self) -> bool:
        """Super key (Windows / Command) is held down."""
        ...

# ── Events ──────────────────────────────────────────────────────────────────

class TaoEvent:
    """Base class for all events dispatched by the event loop.

    Every event carries:
    - :attr:`kind` — an :class:`EventKind` discriminant
    - :attr:`window_id` — the ``int`` identifier of the source window
      (``None`` for events not associated with a window, e.g.
      :class:`UserEvent` and :class:`LoopDestroyedEvent`)

    Use :meth:`TaoWindow.scale_factor` for the live DPI scale factor.
    """

    @property
    def kind(self) -> EventKind:
        """What kind of event this is."""
        ...

    @property
    def window_id(self) -> int | None:
        """The window that triggered this event, or ``None``."""
        ...

class ResizedEvent(TaoEvent):
    """Window client area size changed (physical pixels)."""

    @property
    def width(self) -> float: ...
    @property
    def height(self) -> float: ...

class MovedEvent(TaoEvent):
    """Window outer position changed (physical screen coordinates)."""

    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...

class CloseRequestedEvent(TaoEvent):
    """User clicked the close button or pressed Alt+F4."""

    pass

class DestroyedEvent(TaoEvent):
    """Window has been fully destroyed."""

    pass

class FocusedEvent(TaoEvent):
    """Window gained keyboard focus."""

    pass

class UnfocusedEvent(TaoEvent):
    """Window lost keyboard focus."""

    pass

class ReopenEvent(TaoEvent):
    """The app was reopened via the macOS Dock icon (macOS only).

    Not associated with a specific window — ``window_id`` is ``None``.
    """

    @property
    def has_visible_windows(self) -> bool:
        """Whether any window was visible when the app was reopened."""
        ...

class ScaleFactorChangedEvent(TaoEvent):
    """DPI scale factor changed."""

    @property
    def scale_factor(self) -> float:
        """Current DPI scale factor of the source window."""
        ...

    @property
    def new_scale_factor(self) -> float:
        """The new scale factor value."""
        ...

class ThemeChangedEvent(TaoEvent):
    """System theme changed."""

    @property
    def theme(self) -> Theme: ...

class MouseInputEvent(TaoEvent):
    """Mouse button pressed or released."""

    @property
    def button(self) -> MouseButton: ...
    @property
    def button_code(self) -> int | None:
        """Extra code when ``button == MouseButton.Other``."""
        ...

    @property
    def state(self) -> ElementState: ...
    @property
    def modifiers(self) -> ModifiersState: ...

class CursorMovedEvent(TaoEvent):
    """Cursor moved inside the window."""

    @property
    def x(self) -> float:
        """X coordinate in logical pixels relative to window's top-left."""
        ...

    @property
    def y(self) -> float:
        """Y coordinate in logical pixels relative to window's top-left."""
        ...

    @property
    def modifiers(self) -> ModifiersState:
        """Modifier keys held at the time of the event."""
        ...

class MouseWheelEvent(TaoEvent):
    """Mouse wheel or touchpad scroll."""

    @property
    def delta_kind(self) -> ScrollDeltaKind: ...
    @property
    def dx(self) -> float: ...
    @property
    def dy(self) -> float: ...
    @property
    def phase(self) -> TouchPhase: ...
    @property
    def modifiers(self) -> ModifiersState: ...

class KeyboardInputEvent(TaoEvent):
    """Keyboard key pressed or released."""

    @property
    def physical_key(self) -> str:
        """Scancode / hardware key (e.g. ``"KeyW"``), independent of layout."""
        ...

    @property
    def logical_key(self) -> str:
        """Key with layout applied (e.g. ``"Z"`` on AZERTY for the W key)."""
        ...

    @property
    def text(self) -> str | None:
        """Unicode text produced, if any."""
        ...

    @property
    def state(self) -> ElementState: ...
    @property
    def location(self) -> KeyLocation: ...
    @property
    def repeat(self) -> bool:
        """Whether this is a key-repeat event."""
        ...

    @property
    def is_synthetic(self) -> bool:
        """Whether the OS generated this event (e.g. for focus transitions)."""
        ...

class ModifiersChangedEvent(TaoEvent):
    """Keyboard modifiers changed."""

    @property
    def modifiers(self) -> ModifiersState:
        """The new modifier state."""
        ...

class CursorEnteredEvent(TaoEvent):
    """Cursor entered the window."""

    pass

class CursorLeftEvent(TaoEvent):
    """Cursor left the window."""

    pass

class RedrawRequestedEvent(TaoEvent):
    """The system has requested a window redraw."""

    pass

class UserEvent(TaoEvent):
    """Custom event sent via :meth:`TaoEventLoopProxy.send_event`."""

    @property
    def data(self) -> str:
        """The data string passed to ``send_event()``."""
        ...

class LoopDestroyedEvent(TaoEvent):
    """Sent once after the event loop has exited."""

    pass
