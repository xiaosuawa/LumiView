use pyo3::prelude::*;
use window_vibrancy::NSVisualEffectMaterial;

// EventLoopControl

/// Return this from your event callback to control the event loop.
#[pyclass(eq, frozen, from_py_object)]
#[derive(Clone, PartialEq, Debug)]
pub enum EventLoopControl {
    /// Keep the event loop running.
    Continue,
    /// Stop the event loop cleanly.
    Exit,
}

// EventKind

/// Discriminant for :class:`TaoEvent` — tells you what kind of event occurred.
///
/// Use ``isinstance(event, ResizedEvent)`` for type-safe dispatch instead
/// of matching on this enum directly.
#[pyclass(eq, frozen, skip_from_py_object)]
#[derive(Clone, PartialEq, Debug)]
pub enum EventKind {
    Resized,
    Moved,
    CloseRequested,
    Destroyed,
    Focused,
    Unfocused,
    Reopen,
    ScaleFactorChanged,
    ThemeChanged,
    // Input events
    MouseInput,
    CursorMoved,
    MouseWheel,
    KeyboardInput,
    ModifiersChanged,
    CursorEntered,
    CursorLeft,
    RedrawRequested,
    // Window lifecycle
    Started,
    Suspended,
    Resumed,
    Stopped,
    // Input events (extended)
    ReceivedImeText,
    TouchpadPressure,
    AxisMotion,
    Touch,
    DecorationsClick,
    // Loop-level events
    NewEvents,
    MainEventsCleared,
    RedrawEventsCleared,
    Opened,
    // Device events
    DeviceAdded,
    DeviceRemoved,
    DeviceMouseMotion,
    DeviceMouseWheel,
    DeviceMotion,
    DeviceButton,
    DeviceKey,
    DeviceText,
    // System events
    UserEvent,
    LoopDestroyed,
}

// ModifiersState

/// Keyboard modifier key state snapshot.
///
/// Immutable — each event carries the modifier state at the moment it fired.
/// For live modifier tracking, listen to :class:`ModifiersChangedEvent`.
#[pyclass(frozen, skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct ModifiersState {
    /// Shift key is held down.
    #[pyo3(get)]
    pub shift: bool,
    /// Control key is held down.
    #[pyo3(get)]
    pub ctrl: bool,
    /// Alt key is held down.
    #[pyo3(get)]
    pub alt: bool,
    /// Super key (Windows / Command) is held down.
    #[pyo3(get)]
    pub super_key: bool,
}

impl From<tao::keyboard::ModifiersState> for ModifiersState {
    fn from(m: tao::keyboard::ModifiersState) -> Self {
        ModifiersState {
            shift: m.shift_key(),
            ctrl: m.control_key(),
            alt: m.alt_key(),
            super_key: m.super_key(),
        }
    }
}

#[pymethods]
impl ModifiersState {
    fn __repr__(&self) -> String {
        let mut parts = Vec::new();
        if self.shift {
            parts.push("Shift");
        }
        if self.ctrl {
            parts.push("Ctrl");
        }
        if self.alt {
            parts.push("Alt");
        }
        if self.super_key {
            parts.push("Super");
        }
        if parts.is_empty() {
            "ModifiersState()".into()
        } else {
            format!("ModifiersState({})", parts.join("|"))
        }
    }
}

// Input type enums

macro_rules! simple_enum {
    ($name:ident, $doc:expr, { $($variant:ident => $str:literal),+ $(,)? }) => {
        #[doc = $doc]
        #[pyclass(eq, frozen, hash, skip_from_py_object)]
        #[derive(Clone, PartialEq, Debug, Hash)]
        pub enum $name {
            $($variant),+
        }
    };
}

simple_enum!(
    MouseButton,
    "Mouse button identifier.",
    {
        Left => "Left",
        Right => "Right",
        Middle => "Middle",
        Other => "Other",
    }
);

simple_enum!(
    ElementState,
    "Input element state — pressed or released.",
    {
        Pressed => "Pressed",
        Released => "Released",
    }
);

simple_enum!(
    ScrollDeltaKind,
    "Scroll delta unit — lines or pixels.",
    {
        Line => "Line",
        Pixel => "Pixel",
    }
);

simple_enum!(
    TouchPhase,
    "Touch / scroll gesture phase.",
    {
        Started => "Started",
        Moved => "Moved",
        Ended => "Ended",
        Cancelled => "Cancelled",
    }
);

simple_enum!(
    KeyLocation,
    "Physical key location on the keyboard.",
    {
        Standard => "Standard",
        Left => "Left",
        Right => "Right",
        Numpad => "Numpad",
    }
);

/// System color theme.
///
/// Used as both an event payload (:class:`ThemeChangedEvent`) and an
/// input to :meth:`TaoWindow.set_theme`.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum Theme {
    Light,
    Dark,
}

/// Native background material applied to a window.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum WindowEffect {
    Blur,
    Acrylic,
    Mica,
    Vibrancy,
}

/// Edge or corner used for an interactive window resize.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum ResizeDirection {
    East,
    North,
    NorthEast,
    NorthWest,
    South,
    SouthEast,
    SouthWest,
    West,
}

impl From<ResizeDirection> for tao::window::ResizeDirection {
    fn from(direction: ResizeDirection) -> Self {
        match direction {
            ResizeDirection::East => Self::East,
            ResizeDirection::North => Self::North,
            ResizeDirection::NorthEast => Self::NorthEast,
            ResizeDirection::NorthWest => Self::NorthWest,
            ResizeDirection::South => Self::South,
            ResizeDirection::SouthEast => Self::SouthEast,
            ResizeDirection::SouthWest => Self::SouthWest,
            ResizeDirection::West => Self::West,
        }
    }
}

// From tao impls

impl From<tao::event::ElementState> for ElementState {
    fn from(s: tao::event::ElementState) -> Self {
        match s {
            tao::event::ElementState::Pressed => ElementState::Pressed,
            tao::event::ElementState::Released => ElementState::Released,
            _ => ElementState::Released, // non-exhaustive
        }
    }
}

impl From<tao::event::TouchPhase> for TouchPhase {
    fn from(p: tao::event::TouchPhase) -> Self {
        match p {
            tao::event::TouchPhase::Started => TouchPhase::Started,
            tao::event::TouchPhase::Moved => TouchPhase::Moved,
            tao::event::TouchPhase::Ended => TouchPhase::Ended,
            tao::event::TouchPhase::Cancelled => TouchPhase::Cancelled,
            _ => TouchPhase::Cancelled,
        }
    }
}

impl From<tao::keyboard::KeyLocation> for KeyLocation {
    fn from(l: tao::keyboard::KeyLocation) -> Self {
        match l {
            tao::keyboard::KeyLocation::Standard => KeyLocation::Standard,
            tao::keyboard::KeyLocation::Left => KeyLocation::Left,
            tao::keyboard::KeyLocation::Right => KeyLocation::Right,
            tao::keyboard::KeyLocation::Numpad => KeyLocation::Numpad,
            _ => KeyLocation::Standard,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn element_state_from_tao() {
        assert_eq!(
            ElementState::from(tao::event::ElementState::Pressed),
            ElementState::Pressed
        );
        assert_eq!(
            ElementState::from(tao::event::ElementState::Released),
            ElementState::Released
        );
    }

    #[test]
    fn key_location_from_tao() {
        assert_eq!(
            KeyLocation::from(tao::keyboard::KeyLocation::Standard),
            KeyLocation::Standard
        );
        assert_eq!(
            KeyLocation::from(tao::keyboard::KeyLocation::Left),
            KeyLocation::Left
        );
        assert_eq!(
            KeyLocation::from(tao::keyboard::KeyLocation::Right),
            KeyLocation::Right
        );
        assert_eq!(
            KeyLocation::from(tao::keyboard::KeyLocation::Numpad),
            KeyLocation::Numpad
        );
    }

    #[test]
    fn touch_phase_from_tao() {
        assert_eq!(
            TouchPhase::from(tao::event::TouchPhase::Started),
            TouchPhase::Started
        );
        assert_eq!(
            TouchPhase::from(tao::event::TouchPhase::Moved),
            TouchPhase::Moved
        );
        assert_eq!(
            TouchPhase::from(tao::event::TouchPhase::Ended),
            TouchPhase::Ended
        );
        assert_eq!(
            TouchPhase::from(tao::event::TouchPhase::Cancelled),
            TouchPhase::Cancelled
        );
    }

    #[test]
    fn theme_from_tao() {
        assert_eq!(Theme::from(tao::window::Theme::Light), Theme::Light);
        assert_eq!(Theme::from(tao::window::Theme::Dark), Theme::Dark);
    }

    #[test]
    fn modifiers_state_from_tao() {
        let m = tao::keyboard::ModifiersState::SHIFT | tao::keyboard::ModifiersState::ALT;
        let state = ModifiersState::from(m);
        assert!(state.shift);
        assert!(!state.ctrl);
        assert!(state.alt);
        assert!(!state.super_key);
    }

    #[test]
    fn modifiers_state_empty() {
        let m = tao::keyboard::ModifiersState::empty();
        let state = ModifiersState::from(m);
        assert!(!state.shift);
        assert!(!state.ctrl);
        assert!(!state.alt);
        assert!(!state.super_key);
    }

    #[test]
    fn modifiers_state_repr() {
        let state = ModifiersState {
            shift: true,
            ctrl: true,
            alt: false,
            super_key: false,
        };
        let repr = state.__repr__();
        assert!(repr.contains("Shift"));
        assert!(repr.contains("Ctrl"));
        assert!(!repr.contains("Alt"));
    }

    #[test]
    fn event_loop_control_equality() {
        assert_eq!(EventLoopControl::Continue, EventLoopControl::Continue);
        assert_eq!(EventLoopControl::Exit, EventLoopControl::Exit);
        assert_ne!(EventLoopControl::Continue, EventLoopControl::Exit);
    }

    #[test]
    fn resize_direction_maps_to_tao() {
        assert_eq!(
            tao::window::ResizeDirection::from(ResizeDirection::NorthEast),
            tao::window::ResizeDirection::NorthEast
        );
        assert_eq!(
            tao::window::ResizeDirection::from(ResizeDirection::SouthWest),
            tao::window::ResizeDirection::SouthWest
        );
    }
}

impl From<tao::window::Theme> for Theme {
    fn from(t: tao::window::Theme) -> Self {
        match t {
            tao::window::Theme::Light => Theme::Light,
            tao::window::Theme::Dark => Theme::Dark,
            _ => Theme::Light,
        }
    }
}

// WindowHandleKind

/// Identifies the native window handle type.
#[pyclass(eq, frozen, hash, skip_from_py_object)]
#[derive(Clone, PartialEq, Hash)]
pub enum WindowHandleKind {
    /// Windows HWND.
    Win32,
    /// macOS NSView pointer.
    AppKit,
    /// Linux X11 XID.
    X11,
    /// Linux Wayland wl_surface pointer.
    Wayland,
    /// Linux GTK container pointer (recommended for Wayland compatibility).
    Gtk,
}

// CursorIcon

/// Mouse cursor shape, for :meth:`TaoWindow.set_cursor_icon`.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum CursorIcon {
    Default,
    Crosshair,
    Hand,
    Arrow,
    Move,
    Text,
    Wait,
    Help,
    Progress,
    NotAllowed,
    ContextMenu,
    Cell,
    VerticalText,
    Alias,
    Copy,
    NoDrop,
    Grab,
    Grabbing,
    AllScroll,
    ZoomIn,
    ZoomOut,
    EResize,
    NResize,
    NeResize,
    NwResize,
    SResize,
    SeResize,
    SwResize,
    WResize,
    EwResize,
    NsResize,
    NeswResize,
    NwseResize,
    ColResize,
    RowResize,
}

impl From<CursorIcon> for tao::window::CursorIcon {
    fn from(cursor: CursorIcon) -> Self {
        match cursor {
            CursorIcon::Default => Self::Default,
            CursorIcon::Crosshair => Self::Crosshair,
            CursorIcon::Hand => Self::Hand,
            CursorIcon::Arrow => Self::Arrow,
            CursorIcon::Move => Self::Move,
            CursorIcon::Text => Self::Text,
            CursorIcon::Wait => Self::Wait,
            CursorIcon::Help => Self::Help,
            CursorIcon::Progress => Self::Progress,
            CursorIcon::NotAllowed => Self::NotAllowed,
            CursorIcon::ContextMenu => Self::ContextMenu,
            CursorIcon::Cell => Self::Cell,
            CursorIcon::VerticalText => Self::VerticalText,
            CursorIcon::Alias => Self::Alias,
            CursorIcon::Copy => Self::Copy,
            CursorIcon::NoDrop => Self::NoDrop,
            CursorIcon::Grab => Self::Grab,
            CursorIcon::Grabbing => Self::Grabbing,
            CursorIcon::AllScroll => Self::AllScroll,
            CursorIcon::ZoomIn => Self::ZoomIn,
            CursorIcon::ZoomOut => Self::ZoomOut,
            CursorIcon::EResize => Self::EResize,
            CursorIcon::NResize => Self::NResize,
            CursorIcon::NeResize => Self::NeResize,
            CursorIcon::NwResize => Self::NwResize,
            CursorIcon::SResize => Self::SResize,
            CursorIcon::SeResize => Self::SeResize,
            CursorIcon::SwResize => Self::SwResize,
            CursorIcon::WResize => Self::WResize,
            CursorIcon::EwResize => Self::EwResize,
            CursorIcon::NsResize => Self::NsResize,
            CursorIcon::NeswResize => Self::NeswResize,
            CursorIcon::NwseResize => Self::NwseResize,
            CursorIcon::ColResize => Self::ColResize,
            CursorIcon::RowResize => Self::RowResize,
        }
    }
}

// AttentionType

/// How to draw the user's attention (taskbar flash / Dock bounce).
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum AttentionType {
    /// The user needs a critical response (taskbar flashes until focused).
    Critical,
    /// Informational — the taskbar flashes once.
    Informational,
}

impl From<AttentionType> for tao::window::UserAttentionType {
    fn from(t: AttentionType) -> Self {
        match t {
            AttentionType::Critical => Self::Critical,
            AttentionType::Informational => Self::Informational,
        }
    }
}

// StartCause

/// Why the event loop started a new batch of events.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum StartCause {
    /// The loop was freshly initialized.
    Init,
    /// The loop is polling (continuous refresh).
    Poll,
    /// A ``Wait`` was cancelled before the deadline (external wake).
    WaitCancelled,
    /// A scheduled ``WaitUntil`` deadline was reached.
    ResumeTimeReached,
}

impl From<tao::event::StartCause> for StartCause {
    fn from(cause: tao::event::StartCause) -> Self {
        match cause {
            tao::event::StartCause::Init => StartCause::Init,
            tao::event::StartCause::Poll => StartCause::Poll,
            tao::event::StartCause::WaitCancelled { .. } => StartCause::WaitCancelled,
            tao::event::StartCause::ResumeTimeReached { .. } => StartCause::ResumeTimeReached,
            _ => StartCause::Init,
        }
    }
}

// ProgressState

/// Taskbar progress bar state (Windows).
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum ProgressState {
    /// Determinate progress (see the ``progress`` value).
    Normal,
    /// Indeterminate animation (no value shown).
    Indeterminate,
    /// Paused (yellow).
    Paused,
    /// Error (red).
    Error,
}

impl From<ProgressState> for tao::window::ProgressState {
    fn from(state: ProgressState) -> Self {
        match state {
            ProgressState::Normal => Self::Normal,
            ProgressState::Indeterminate => Self::Indeterminate,
            ProgressState::Paused => Self::Paused,
            ProgressState::Error => Self::Error,
        }
    }
}

// VibrancyMaterial

/// macOS ``NSVisualEffectMaterial`` — the background material used by
/// :meth:`TaoWindow.apply_effect` with ``WindowEffect.Vibrancy``.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum VibrancyMaterial {
    /// Default material for the view's appearance.
    AppearanceBased,
    Titlebar,
    Selection,
    Menu,
    Popover,
    Sidebar,
    HeaderView,
    Sheet,
    WindowBackground,
    HudWindow,
    FullScreenUI,
    Tooltip,
    ContentBackground,
    UnderWindowBackground,
    UnderPageBackground,
}

impl From<VibrancyMaterial> for NSVisualEffectMaterial {
    #[allow(deprecated)] // AppearanceBased is marked deprecated upstream
    fn from(material: VibrancyMaterial) -> Self {
        match material {
            VibrancyMaterial::AppearanceBased => Self::AppearanceBased,
            VibrancyMaterial::Titlebar => Self::Titlebar,
            VibrancyMaterial::Selection => Self::Selection,
            VibrancyMaterial::Menu => Self::Menu,
            VibrancyMaterial::Popover => Self::Popover,
            VibrancyMaterial::Sidebar => Self::Sidebar,
            VibrancyMaterial::HeaderView => Self::HeaderView,
            VibrancyMaterial::Sheet => Self::Sheet,
            VibrancyMaterial::WindowBackground => Self::WindowBackground,
            VibrancyMaterial::HudWindow => Self::HudWindow,
            VibrancyMaterial::FullScreenUI => Self::FullScreenUI,
            VibrancyMaterial::Tooltip => Self::Tooltip,
            VibrancyMaterial::ContentBackground => Self::ContentBackground,
            VibrancyMaterial::UnderWindowBackground => Self::UnderWindowBackground,
            VibrancyMaterial::UnderPageBackground => Self::UnderPageBackground,
        }
    }
}

// ActivationPolicy

/// App activation policy — macOS only (regular app, accessory/agent app,
/// or prohibited). Passed to :meth:`TaoEventLoop.set_activation_policy`
/// **before** the event loop runs.
#[pyclass(eq, frozen, hash, from_py_object)]
#[derive(Clone, PartialEq, Debug, Hash)]
pub enum ActivationPolicy {
    /// Regular app with a Dock icon and a menu bar.
    Regular,
    /// Accessory app: no Dock icon, no menu bar (agent apps, menu bar apps).
    Accessory,
    /// Prohibited: the app cannot be activated at all.
    Prohibited,
}

#[cfg(target_os = "macos")]
impl From<ActivationPolicy> for tao::platform::macos::ActivationPolicy {
    fn from(policy: ActivationPolicy) -> Self {
        match policy {
            ActivationPolicy::Regular => Self::Regular,
            ActivationPolicy::Accessory => Self::Accessory,
            ActivationPolicy::Prohibited => Self::Prohibited,
        }
    }
}

// Tray conversions (tray-icon's enums are subsets of tao's)

impl From<tray_icon::MouseButton> for MouseButton {
    fn from(button: tray_icon::MouseButton) -> Self {
        match button {
            tray_icon::MouseButton::Left => MouseButton::Left,
            tray_icon::MouseButton::Right => MouseButton::Right,
            tray_icon::MouseButton::Middle => MouseButton::Middle,
        }
    }
}

impl From<tray_icon::MouseButtonState> for ElementState {
    fn from(state: tray_icon::MouseButtonState) -> Self {
        match state {
            tray_icon::MouseButtonState::Up => ElementState::Released,
            tray_icon::MouseButtonState::Down => ElementState::Pressed,
        }
    }
}
