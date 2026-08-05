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

    # Monitors (valid while run() is active)
    def available_monitors(self) -> list["Monitor"]:
        """All monitors currently connected."""
        ...
    def primary_monitor(self) -> "Monitor | None":
        """The primary monitor, if any."""
        ...
    def monitor_from_point(self, x: float, y: float) -> "Monitor | None":
        """The monitor that contains the given physical screen point."""
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
        material: "VibrancyMaterial | None" = None,
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

    # Geometry
    def inner_position(self) -> tuple[float, float]:
        """Logical inner position, relative to the screen top-left.

        Raises ``NotImplementedError`` on platforms that cannot report
        it (Wayland).
        """
        ...
    def outer_position(self) -> tuple[float, float]:
        """Logical outer position, relative to the screen top-left."""
        ...
    def cursor_position(self) -> tuple[float, float]:
        """Logical cursor position inside the client area."""
        ...

    # Appearance / state
    def title(self) -> str:
        """The current window title."""
        ...
    def theme(self) -> "Theme":
        """The window's effective color theme."""
        ...
    def set_theme(self, theme: "Theme | None") -> None:
        """Force the window theme (None restores the system default)."""
        ...
    def is_focused(self) -> bool: ...
    def is_resizable(self) -> bool: ...
    def is_decorated(self) -> bool: ...
    def is_closable(self) -> bool: ...
    def is_minimizable(self) -> bool: ...
    def is_maximizable(self) -> bool: ...
    def is_always_on_top(self) -> bool: ...
    def is_fullscreen(self) -> bool: ...
    def set_focusable(self, focusable: bool) -> None: ...
    def set_content_protection(self, enabled: bool) -> None: ...
    def set_visible_on_all_workspaces(self, visible: bool) -> None: ...
    def set_always_on_bottom(self, always: bool) -> None: ...

    # Cursor
    def set_cursor_icon(self, cursor: "CursorIcon") -> None: ...
    def set_cursor_grab(self, grab: bool) -> None: ...
    def set_ignore_cursor_events(self, ignore: bool) -> None: ...
    def set_cursor_position(self, x: float, y: float) -> None: ...

    # Attention / IME
    def request_user_attention(self, request_type: "AttentionType | None") -> None:
        """Ask the OS to draw the user's attention (None clears it)."""
        ...
    def set_ime_position(self, x: float, y: float) -> None: ...

    # Fullscreen
    def set_borderless_fullscreen(self, monitor: "Monitor | None") -> None:
        """Borderless fullscreen on *monitor* (None = current)."""
        ...
    def set_exclusive_fullscreen(self, mode: "VideoMode") -> None:
        """Exclusive fullscreen at the mode's resolution/refresh rate."""
        ...

    # Progress bar (Windows taskbar)
    def set_progress_bar(
        self,
        state: "ProgressState | None",
        progress: "float | None",
    ) -> None:
        """Set the taskbar progress bar (state=None removes it)."""
        ...

    # Monitors
    def current_monitor(self) -> "Monitor | None": ...
    def available_monitors(self) -> "list[Monitor]": ...
    def primary_monitor(self) -> "Monitor | None": ...
    def monitor_from_point(self, x: float, y: float) -> "Monitor | None": ...

    # Windows only
    def set_skip_taskbar(self, skip: bool) -> None: ...
    def set_taskbar_icon(self, icon: "tuple[int, int, bytes] | None") -> None:
        """(width, height, rgba); None restores the window icon."""
        ...
    def set_overlay_icon(self, icon: "tuple[int, int, bytes] | None") -> None:
        """(width, height, rgba); None removes the overlay."""
        ...
    def set_enable(self, enabled: bool) -> None: ...
    def set_rtl(self, rtl: bool) -> None: ...
    def reset_dead_keys(self) -> None: ...
    def set_undecorated_shadow(self, shadow: bool) -> None: ...
    def has_undecorated_shadow(self) -> bool: ...

    # macOS only
    def set_badge_label(self, label: "str | None") -> None: ...
    def set_simple_fullscreen(self, fullscreen: bool) -> bool:
        """Toggle simple fullscreen; returns the resulting state."""
        ...
    def set_titlebar_transparent(self, transparent: bool) -> None: ...
    def set_traffic_light_inset(self, x: float, y: float) -> None: ...
    def set_has_shadow(self, has_shadow: bool) -> None: ...
    def has_shadow(self) -> bool: ...

    # Linux only
    def set_badge_count(self, count: "int | None") -> None: ...

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
    Started: EventKind
    Suspended: EventKind
    Resumed: EventKind
    Stopped: EventKind
    ReceivedImeText: EventKind
    TouchpadPressure: EventKind
    AxisMotion: EventKind
    Touch: EventKind
    DecorationsClick: EventKind
    NewEvents: EventKind
    MainEventsCleared: EventKind
    RedrawEventsCleared: EventKind
    Opened: EventKind
    DeviceAdded: EventKind
    DeviceRemoved: EventKind
    DeviceMouseMotion: EventKind
    DeviceMouseWheel: EventKind
    DeviceMotion: EventKind
    DeviceButton: EventKind
    DeviceKey: EventKind
    DeviceText: EventKind
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
    """System color theme.

    Used as both an event payload and an input to
    :meth:`TaoWindow.set_theme`.
    """

    Light: Theme
    Dark: Theme

class CursorIcon(Enum):
    """Mouse cursor shape."""

    Default: CursorIcon
    Crosshair: CursorIcon
    Hand: CursorIcon
    Arrow: CursorIcon
    Move: CursorIcon
    Text: CursorIcon
    Wait: CursorIcon
    Help: CursorIcon
    Progress: CursorIcon
    NotAllowed: CursorIcon
    ContextMenu: CursorIcon
    Cell: CursorIcon
    VerticalText: CursorIcon
    Alias: CursorIcon
    Copy: CursorIcon
    NoDrop: CursorIcon
    Grab: CursorIcon
    Grabbing: CursorIcon
    AllScroll: CursorIcon
    ZoomIn: CursorIcon
    ZoomOut: CursorIcon
    EResize: CursorIcon
    NResize: CursorIcon
    NeResize: CursorIcon
    NwResize: CursorIcon
    SResize: CursorIcon
    SeResize: CursorIcon
    SwResize: CursorIcon
    WResize: CursorIcon
    EwResize: CursorIcon
    NsResize: CursorIcon
    NeswResize: CursorIcon
    NwseResize: CursorIcon
    ColResize: CursorIcon
    RowResize: CursorIcon

class AttentionType(Enum):
    """How to draw the user's attention."""

    Critical: AttentionType
    Informational: AttentionType

class StartCause(Enum):
    """Why the event loop started a new batch of events."""

    Init: StartCause
    Poll: StartCause
    WaitCancelled: StartCause
    ResumeTimeReached: StartCause

class ProgressState(Enum):
    """Taskbar progress bar state (Windows)."""

    Normal: ProgressState
    Indeterminate: ProgressState
    Paused: ProgressState
    Error: ProgressState

class VibrancyMaterial(Enum):
    """macOS NSVisualEffectMaterial for ``WindowEffect.Vibrancy``."""

    AppearanceBased: VibrancyMaterial
    Titlebar: VibrancyMaterial
    Selection: VibrancyMaterial
    Menu: VibrancyMaterial
    Popover: VibrancyMaterial
    Sidebar: VibrancyMaterial
    HeaderView: VibrancyMaterial
    Sheet: VibrancyMaterial
    WindowBackground: VibrancyMaterial
    HudWindow: VibrancyMaterial
    FullScreenUI: VibrancyMaterial
    Tooltip: VibrancyMaterial
    ContentBackground: VibrancyMaterial
    UnderWindowBackground: VibrancyMaterial
    UnderPageBackground: VibrancyMaterial

class Monitor:
    """A display monitor connected to the system.

    Size and position are in physical pixels; use
    :meth:`scale_factor` to convert.
    """

    def name(self) -> str | None:
        """Human-readable monitor name, if known."""
        ...
    def size(self) -> tuple[int, int]:
        """Physical size in pixels."""
        ...
    def position(self) -> tuple[int, int]:
        """Physical position of the top-left corner."""
        ...
    def scale_factor(self) -> float:
        """DPI scale factor of this monitor."""
        ...
    def video_modes(self) -> list["VideoMode"]:
        """All display modes supported by this monitor, best first."""
        ...

class VideoMode:
    """A display mode (resolution + refresh rate + color depth)."""

    def size(self) -> tuple[int, int]:
        """Resolution in physical pixels."""
        ...
    def bit_depth(self) -> int:
        """Color depth in bits per pixel."""
        ...
    def refresh_rate(self) -> int:
        """Refresh rate in Hertz."""
        ...
    def monitor(self) -> Monitor:
        """The monitor this mode belongs to."""
        ...

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
        """The new DPI scale factor."""
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

# ── Extended events ─────────────────────────────────────────────────────────

class StartedEvent(TaoEvent):
    """The window started (became active)."""

    pass

class SuspendedEvent(TaoEvent):
    """The window was suspended."""

    pass

class ResumedEvent(TaoEvent):
    """The window resumed from suspension."""

    pass

class StoppedEvent(TaoEvent):
    """The window stopped."""

    pass

class DecorationsClickEvent(TaoEvent):
    """The user double-clicked the window decorations (Windows)."""

    pass

class ReceivedImeTextEvent(TaoEvent):
    """Input method editor (IME) text arrived."""

    @property
    def text(self) -> str:
        """The IME pre-edit / committed text."""
        ...

class TouchpadPressureEvent(TaoEvent):
    """Touchpad pressure changed (macOS)."""

    @property
    def pressure(self) -> float:
        """Normalized pressure 0.0–1.0."""
        ...
    @property
    def stage(self) -> int:
        """Pressure stage (1 = light, 2 = deep click)."""
        ...

class AxisMotionEvent(TaoEvent):
    """Joystick / additional input axis motion."""

    @property
    def axis(self) -> int:
        """The axis identifier."""
        ...
    @property
    def value(self) -> float:
        """The axis position (typically -1.0–1.0)."""
        ...

class TouchEvent(TaoEvent):
    """A touch contact on a touch screen."""

    @property
    def phase(self) -> TouchPhase: ...
    @property
    def x(self) -> float:
        """Logical x position inside the window."""
        ...
    @property
    def y(self) -> float:
        """Logical y position inside the window."""
        ...
    @property
    def force(self) -> float | None:
        """Pressure 0.0–1.0, or None if not reported."""
        ...
    @property
    def id(self) -> int:
        """Unique finger identifier."""
        ...

class NewEventsEvent(TaoEvent):
    """The event loop started a new batch of events."""

    @property
    def cause(self) -> StartCause:
        """Why the batch started."""
        ...

class MainEventsClearedEvent(TaoEvent):
    """All events of the current batch were processed."""

    pass

class RedrawEventsClearedEvent(TaoEvent):
    """All redraw requests of the current frame were processed."""

    pass

class OpenedEvent(TaoEvent):
    """The app was opened with a URL (custom scheme / file association)."""

    @property
    def urls(self) -> list[str]:
        """The URLs the app was opened with."""
        ...

class DeviceAddedEvent(TaoEvent):
    """An input device was connected."""

    pass

class DeviceRemovedEvent(TaoEvent):
    """An input device was disconnected."""

    pass

class DeviceMouseMotionEvent(TaoEvent):
    """Global (device-level) mouse motion."""

    @property
    def dx(self) -> float: ...
    @property
    def dy(self) -> float: ...

class DeviceMouseWheelEvent(TaoEvent):
    """Global (device-level) mouse wheel."""

    @property
    def delta_kind(self) -> ScrollDeltaKind: ...
    @property
    def dx(self) -> float: ...
    @property
    def dy(self) -> float: ...

class DeviceMotionEvent(TaoEvent):
    """Global (device-level) axis motion."""

    @property
    def axis(self) -> int: ...
    @property
    def value(self) -> float: ...

class DeviceButtonEvent(TaoEvent):
    """Global (device-level) mouse button."""

    @property
    def button(self) -> int: ...
    @property
    def state(self) -> ElementState: ...

class DeviceKeyEvent(TaoEvent):
    """Global (device-level) keyboard event."""

    @property
    def physical_key(self) -> str:
        """The hardware key (e.g. ``"KeyW"``)."""
        ...
    @property
    def state(self) -> ElementState: ...

class DeviceTextEvent(TaoEvent):
    """Global (device-level) text input."""

    @property
    def codepoint(self) -> int:
        """The Unicode code point of the character."""
        ...

# ── Functions ───────────────────────────────────────────────────────────────

def parse_key_code(text: str) -> str | None:
    """Parse a key-code name (e.g. ``"KeyW"``, ``"Space"``, ``"A"``)
    into its canonical form, or ``None`` if unknown. Case-insensitive."""
    ...
