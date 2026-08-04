use pyo3::prelude::*;

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

simple_enum!(
    Theme,
    "System color theme.",
    {
        Light => "Light",
        Dark => "Dark",
    }
);

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
        let repr = format!("{}", state.__repr__());
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
