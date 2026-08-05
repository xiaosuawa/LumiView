use std::hash::{Hash, Hasher};

use pyo3::prelude::*;
use tao::event::{Event, WindowEvent};
use tao::window::WindowId;

use crate::types::{
    ElementState, EventKind, KeyLocation, ModifiersState, MouseButton, ScrollDeltaKind,
    StartCause, Theme, TouchPhase,
};

// WindowId → u64

fn wid_to_u64(wid: &WindowId) -> u64 {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    wid.hash(&mut h);
    h.finish()
}

#[cfg(test)]
mod tests {
    use super::wid_to_u64;
    use tao::window::WindowId;

    #[test]
    fn window_id_hashing_is_deterministic() {
        let wid = unsafe { WindowId::dummy() };
        let h1 = wid_to_u64(&wid);
        let h2 = wid_to_u64(&wid);
        assert_eq!(h1, h2);
    }

    #[test]
    fn window_id_is_nonzero() {
        let wid = unsafe { WindowId::dummy() };
        let h = wid_to_u64(&wid);
        assert_ne!(h, 0, "WindowId hash should be non-zero");
    }
}

// TaoEvent (base)

/// Base class for all events dispatched by the event loop.
///
/// Every event carries:
/// - :attr:`kind` — an :class:`EventKind` discriminant
/// - :attr:`window_id` — the source window's ``int`` identifier
///   (``None`` for events not associated with a window)
///
/// Use ``isinstance(event, ResizedEvent)`` to dispatch and get typed fields.
///
/// Use :meth:`TaoWindow.scale_factor` for the live DPI scale factor.
#[pyclass(subclass)]
pub struct TaoEvent {
    pub kind: EventKind,
    pub window_id: Option<u64>,
}

#[pymethods]
impl TaoEvent {
    #[getter]
    fn kind(&self) -> EventKind {
        self.kind.clone()
    }

    #[getter]
    fn window_id(&self) -> Option<u64> {
        self.window_id
    }

    fn __repr__(&self) -> String {
        format!("TaoEvent({:?})", self.kind)
    }
}

// Event subclass boilerplate

macro_rules! empty_event {
    ($name:ident, $doc:expr) => {
        #[doc = $doc]
        #[pyclass(extends = TaoEvent)]
        pub struct $name {}

        #[pymethods]
        impl $name {}
    };
}

// Geometry events

/// Window client area size changed (physical pixels).
///
/// Use :meth:`TaoWindow.scale_factor` to convert to logical pixels.
#[pyclass(extends = TaoEvent)]
pub struct ResizedEvent {
    #[pyo3(get)]
    pub width: f64,
    #[pyo3(get)]
    pub height: f64,
}

#[pymethods]
impl ResizedEvent {
    fn __repr__(&self) -> String {
        format!("ResizedEvent({}×{})", self.width, self.height)
    }
}

/// Window outer position changed (physical screen coordinates).
#[pyclass(extends = TaoEvent)]
pub struct MovedEvent {
    #[pyo3(get)]
    pub x: f64,
    #[pyo3(get)]
    pub y: f64,
}

#[pymethods]
impl MovedEvent {
    fn __repr__(&self) -> String {
        format!("MovedEvent(x={}, y={})", self.x, self.y)
    }
}

// Lifecycle events

empty_event!(
    CloseRequestedEvent,
    "User clicked the close button or pressed Alt+F4."
);
empty_event!(DestroyedEvent, "Window has been fully destroyed.");
empty_event!(FocusedEvent, "Window gained keyboard focus.");
empty_event!(UnfocusedEvent, "Window lost keyboard focus.");

/// macOS only — the app was reopened (user clicked the Dock icon).
///
/// Not associated with a specific window: ``window_id`` is ``None`` and
/// :attr:`has_visible_windows` reports whether any window was visible at
/// reopen time.
#[pyclass(extends = TaoEvent)]
pub struct ReopenEvent {
    #[pyo3(get)]
    pub has_visible_windows: bool,
}

#[pymethods]
impl ReopenEvent {
    fn __repr__(&self) -> String {
        format!(
            "ReopenEvent(has_visible_windows={})",
            self.has_visible_windows
        )
    }
}

/// DPI scale factor changed.
///
/// The old factor equals the base :attr:`TaoEvent.scale_factor`; this
/// field carries the new one.
#[pyclass(extends = TaoEvent)]
pub struct ScaleFactorChangedEvent {
    #[pyo3(get)]
    pub scale_factor: f64,
}

#[pymethods]
impl ScaleFactorChangedEvent {
    fn __repr__(&self) -> String {
        format!("ScaleFactorChangedEvent(sf={})", self.scale_factor)
    }
}

/// System theme changed.
#[pyclass(extends = TaoEvent)]
pub struct ThemeChangedEvent {
    #[pyo3(get)]
    pub theme: Theme,
}

#[pymethods]
impl ThemeChangedEvent {
    fn __repr__(&self) -> String {
        format!("ThemeChangedEvent({:?})", self.theme)
    }
}

// Input events

/// Mouse button pressed or released.
#[pyclass(extends = TaoEvent)]
pub struct MouseInputEvent {
    #[pyo3(get)]
    pub button: MouseButton,
    #[pyo3(get)]
    pub button_code: Option<u16>,
    #[pyo3(get)]
    pub state: ElementState,
    #[pyo3(get)]
    pub modifiers: ModifiersState,
}

#[pymethods]
impl MouseInputEvent {
    fn __repr__(&self) -> String {
        format!("MouseInputEvent({:?} {:?})", self.button, self.state)
    }
}

/// Cursor moved inside the window.
#[pyclass(extends = TaoEvent)]
pub struct CursorMovedEvent {
    #[pyo3(get)]
    pub x: f64,
    #[pyo3(get)]
    pub y: f64,
    #[pyo3(get)]
    pub modifiers: ModifiersState,
}

#[pymethods]
impl CursorMovedEvent {
    fn __repr__(&self) -> String {
        format!("CursorMovedEvent(x={:.1}, y={:.1})", self.x, self.y)
    }
}

/// Mouse wheel or touchpad scroll.
#[pyclass(extends = TaoEvent)]
pub struct MouseWheelEvent {
    #[pyo3(get)]
    pub delta_kind: ScrollDeltaKind,
    #[pyo3(get)]
    pub dx: f64,
    #[pyo3(get)]
    pub dy: f64,
    #[pyo3(get)]
    pub phase: TouchPhase,
    #[pyo3(get)]
    pub modifiers: ModifiersState,
}

#[pymethods]
impl MouseWheelEvent {
    fn __repr__(&self) -> String {
        format!(
            "MouseWheelEvent({:?} dx={:.1}, dy={:.1})",
            self.delta_kind, self.dx, self.dy
        )
    }
}

/// Keyboard key pressed or released.
#[pyclass(extends = TaoEvent)]
pub struct KeyboardInputEvent {
    #[pyo3(get)]
    pub physical_key: String,
    #[pyo3(get)]
    pub logical_key: String,
    #[pyo3(get)]
    pub text: Option<String>,
    #[pyo3(get)]
    pub state: ElementState,
    #[pyo3(get)]
    pub location: KeyLocation,
    #[pyo3(get)]
    pub repeat: bool,
    #[pyo3(get)]
    pub is_synthetic: bool,
}

#[pymethods]
impl KeyboardInputEvent {
    fn __repr__(&self) -> String {
        if let Some(ref _text) = self.text {
            format!(
                "KeyboardInputEvent({:?} {:?})",
                self.logical_key, self.state
            )
        } else {
            format!(
                "KeyboardInputEvent({:?} {:?} {:?})",
                self.physical_key, self.state, self.logical_key,
            )
        }
    }
}

/// Keyboard modifiers changed (Shift, Ctrl, Alt, Super).
#[pyclass(extends = TaoEvent)]
pub struct ModifiersChangedEvent {
    #[pyo3(get)]
    pub modifiers: ModifiersState,
}

#[pymethods]
impl ModifiersChangedEvent {
    fn __repr__(&self) -> String {
        format!("ModifiersChangedEvent({:?})", self.modifiers)
    }
}

// Cursor boundary events

empty_event!(CursorEnteredEvent, "Cursor entered the window.");
empty_event!(CursorLeftEvent, "Cursor left the window.");

// Redraw event

empty_event!(
    RedrawRequestedEvent,
    "The system has requested a window redraw."
);

// User event

/// Custom event sent via :meth:`TaoEventLoopProxy.send_event`.
#[pyclass(extends = TaoEvent)]
pub struct UserEvent {
    #[pyo3(get)]
    pub data: String,
}

#[pymethods]
impl UserEvent {
    fn __repr__(&self) -> String {
        format!("UserEvent({})", self.data)
    }
}

// Loop destroyed

empty_event!(
    LoopDestroyedEvent,
    "Sent once after the event loop has exited."
);

// Window lifecycle events

empty_event!(StartedEvent, "The window started (became active).");
empty_event!(SuspendedEvent, "The window was suspended.");
empty_event!(ResumedEvent, "The window resumed from suspension.");
empty_event!(StoppedEvent, "The window stopped.");
empty_event!(
    DecorationsClickEvent,
    "The user double-clicked the window decorations (Windows)."
);

/// Input method editor (IME) text arrived — the pre-edit / committed
/// string of a composition session.
#[pyclass(extends = TaoEvent)]
pub struct ReceivedImeTextEvent {
    #[pyo3(get)]
    pub text: String,
}

#[pymethods]
impl ReceivedImeTextEvent {
    fn __repr__(&self) -> String {
        format!("ReceivedImeTextEvent({:?})", self.text)
    }
}

/// Touchpad pressure event (macOS).
#[pyclass(extends = TaoEvent)]
pub struct TouchpadPressureEvent {
    #[pyo3(get)]
    pub pressure: f64,
    #[pyo3(get)]
    pub stage: i64,
}

#[pymethods]
impl TouchpadPressureEvent {
    fn __repr__(&self) -> String {
        format!("TouchpadPressureEvent(pressure={:.2}, stage={})", self.pressure, self.stage)
    }
}

/// Joystick / additional input axis motion.
#[pyclass(extends = TaoEvent)]
pub struct AxisMotionEvent {
    #[pyo3(get)]
    pub axis: u32,
    #[pyo3(get)]
    pub value: f64,
}

#[pymethods]
impl AxisMotionEvent {
    fn __repr__(&self) -> String {
        format!("AxisMotionEvent(axis={}, value={:.2})", self.axis, self.value)
    }
}

/// A touch contact on a touch screen.
#[pyclass(extends = TaoEvent)]
pub struct TouchEvent {
    #[pyo3(get)]
    pub phase: TouchPhase,
    /// Logical position inside the window.
    #[pyo3(get)]
    pub x: f64,
    #[pyo3(get)]
    pub y: f64,
    /// Pressure 0.0–1.0, when the platform reports it.
    #[pyo3(get)]
    pub force: Option<f64>,
    /// Unique finger identifier.
    #[pyo3(get)]
    pub id: u64,
}

#[pymethods]
impl TouchEvent {
    fn __repr__(&self) -> String {
        format!(
            "TouchEvent({:?} ({:.1}, {:.1}) id={})",
            self.phase, self.x, self.y, self.id
        )
    }
}

// Loop-level events

/// The event loop started a new batch of events.
#[pyclass(extends = TaoEvent)]
pub struct NewEventsEvent {
    #[pyo3(get)]
    pub cause: StartCause,
}

#[pymethods]
impl NewEventsEvent {
    fn __repr__(&self) -> String {
        format!("NewEventsEvent({:?})", self.cause)
    }
}

empty_event!(
    MainEventsClearedEvent,
    "All events of the current batch were processed."
);
empty_event!(
    RedrawEventsClearedEvent,
    "All redraw events of the current frame were processed."
);

/// The application was opened with a URL (e.g. custom scheme /
/// file association).
#[pyclass(extends = TaoEvent)]
pub struct OpenedEvent {
    #[pyo3(get)]
    pub urls: Vec<String>,
}

#[pymethods]
impl OpenedEvent {
    fn __repr__(&self) -> String {
        format!("OpenedEvent({:?})", self.urls)
    }
}

// Device events (global input devices)

empty_event!(DeviceAddedEvent, "An input device was connected.");
empty_event!(DeviceRemovedEvent, "An input device was disconnected.");

/// Global (device-level) mouse motion.
#[pyclass(extends = TaoEvent)]
pub struct DeviceMouseMotionEvent {
    #[pyo3(get)]
    pub dx: f64,
    #[pyo3(get)]
    pub dy: f64,
}

#[pymethods]
impl DeviceMouseMotionEvent {
    fn __repr__(&self) -> String {
        format!("DeviceMouseMotionEvent(dx={:.1}, dy={:.1})", self.dx, self.dy)
    }
}

/// Global (device-level) mouse wheel.
#[pyclass(extends = TaoEvent)]
pub struct DeviceMouseWheelEvent {
    #[pyo3(get)]
    pub delta_kind: ScrollDeltaKind,
    #[pyo3(get)]
    pub dx: f64,
    #[pyo3(get)]
    pub dy: f64,
}

#[pymethods]
impl DeviceMouseWheelEvent {
    fn __repr__(&self) -> String {
        format!(
            "DeviceMouseWheelEvent({:?} dx={:.1}, dy={:.1})",
            self.delta_kind, self.dx, self.dy
        )
    }
}

/// Global (device-level) axis motion.
#[pyclass(extends = TaoEvent)]
pub struct DeviceMotionEvent {
    #[pyo3(get)]
    pub axis: u32,
    #[pyo3(get)]
    pub value: f64,
}

#[pymethods]
impl DeviceMotionEvent {
    fn __repr__(&self) -> String {
        format!("DeviceMotionEvent(axis={}, value={:.2})", self.axis, self.value)
    }
}

/// Global (device-level) mouse button.
#[pyclass(extends = TaoEvent)]
pub struct DeviceButtonEvent {
    #[pyo3(get)]
    pub button: u32,
    #[pyo3(get)]
    pub state: ElementState,
}

#[pymethods]
impl DeviceButtonEvent {
    fn __repr__(&self) -> String {
        format!("DeviceButtonEvent({} {:?})", self.button, self.state)
    }
}

/// Global (device-level) keyboard event.
#[pyclass(extends = TaoEvent)]
pub struct DeviceKeyEvent {
    #[pyo3(get)]
    pub physical_key: String,
    #[pyo3(get)]
    pub state: ElementState,
}

#[pymethods]
impl DeviceKeyEvent {
    fn __repr__(&self) -> String {
        format!("DeviceKeyEvent({:?} {:?})", self.physical_key, self.state)
    }
}

/// Global (device-level) text input.
#[pyclass(extends = TaoEvent)]
pub struct DeviceTextEvent {
    #[pyo3(get)]
    pub codepoint: u32,
}

#[pymethods]
impl DeviceTextEvent {
    fn __repr__(&self) -> String {
        format!("DeviceTextEvent({})", self.codepoint)
    }
}

// build_event — type-driven factory

pub fn build_event(py: Python<'_>, event: &Event<'_, String>) -> Option<Py<PyAny>> {
    match event {
        Event::WindowEvent {
            window_id,
            event: we,
            ..
        } => {
            let wid = wid_to_u64(window_id);

            match we {
                WindowEvent::Resized(size) => {
                    let base = TaoEvent {
                        kind: EventKind::Resized,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(ResizedEvent {
                        width: size.width as f64,
                        height: size.height as f64,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Moved(pos) => {
                    let base = TaoEvent {
                        kind: EventKind::Moved,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(MovedEvent {
                        x: pos.x as f64,
                        y: pos.y as f64,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::CloseRequested => {
                    let base = TaoEvent {
                        kind: EventKind::CloseRequested,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(CloseRequestedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Destroyed => {
                    let base = TaoEvent {
                        kind: EventKind::Destroyed,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DestroyedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Focused(true) => {
                    let base = TaoEvent {
                        kind: EventKind::Focused,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(FocusedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Focused(false) => {
                    let base = TaoEvent {
                        kind: EventKind::Unfocused,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(UnfocusedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::ScaleFactorChanged { scale_factor, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::ScaleFactorChanged,
                        window_id: Some(wid),
                    };
                    let init =
                        PyClassInitializer::from(base).add_subclass(ScaleFactorChangedEvent {
                            scale_factor: *scale_factor,
                        });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::ThemeChanged(t) => {
                    let theme = Theme::from(*t);
                    let base = TaoEvent {
                        kind: EventKind::ThemeChanged,
                        window_id: Some(wid),
                    };
                    let init =
                        PyClassInitializer::from(base).add_subclass(ThemeChangedEvent { theme });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                #[allow(deprecated)]
                WindowEvent::MouseInput {
                    button,
                    state,
                    modifiers,
                    ..
                } => {
                    let base = TaoEvent {
                        kind: EventKind::MouseInput,
                        window_id: Some(wid),
                    };
                    let (btn, code) = match button {
                        tao::event::MouseButton::Left => (MouseButton::Left, None),
                        tao::event::MouseButton::Right => (MouseButton::Right, None),
                        tao::event::MouseButton::Middle => (MouseButton::Middle, None),
                        tao::event::MouseButton::Other(n) => (MouseButton::Other, Some(*n)),
                        _ => (MouseButton::Other, None),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(MouseInputEvent {
                        button: btn,
                        button_code: code,
                        state: ElementState::from(*state),
                        modifiers: ModifiersState::from(*modifiers),
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                #[allow(deprecated)]
                WindowEvent::CursorMoved {
                    position,
                    modifiers,
                    ..
                } => {
                    let base = TaoEvent {
                        kind: EventKind::CursorMoved,
                        window_id: Some(wid),
                    };
                    let mods = ModifiersState::from(*modifiers);
                    let init = PyClassInitializer::from(base).add_subclass(CursorMovedEvent {
                        x: position.x,
                        y: position.y,
                        modifiers: mods,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                #[allow(deprecated)]
                WindowEvent::MouseWheel {
                    delta,
                    phase,
                    modifiers,
                    ..
                } => {
                    let base = TaoEvent {
                        kind: EventKind::MouseWheel,
                        window_id: Some(wid),
                    };
                    let (kind, dx, dy) = match delta {
                        tao::event::MouseScrollDelta::LineDelta(x, y) => {
                            (ScrollDeltaKind::Line, *x as f64, *y as f64)
                        }
                        tao::event::MouseScrollDelta::PixelDelta(pos) => {
                            (ScrollDeltaKind::Pixel, pos.x, pos.y)
                        }
                        _ => (ScrollDeltaKind::Line, 0.0, 0.0),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(MouseWheelEvent {
                        delta_kind: kind,
                        dx,
                        dy,
                        phase: TouchPhase::from(*phase),
                        modifiers: ModifiersState::from(*modifiers),
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::KeyboardInput {
                    event: key_event,
                    is_synthetic,
                    ..
                } => {
                    let base = TaoEvent {
                        kind: EventKind::KeyboardInput,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(KeyboardInputEvent {
                        physical_key: key_event.physical_key.to_string(),
                        logical_key: format!("{:?}", key_event.logical_key),
                        text: key_event.text.map(|s| s.to_string()),
                        state: ElementState::from(key_event.state),
                        location: KeyLocation::from(key_event.location),
                        repeat: key_event.repeat,
                        is_synthetic: *is_synthetic,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::ModifiersChanged(modifiers) => {
                    let base = TaoEvent {
                        kind: EventKind::ModifiersChanged,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(ModifiersChangedEvent {
                        modifiers: ModifiersState::from(*modifiers),
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::CursorEntered { .. } => {
                    let base = TaoEvent {
                        kind: EventKind::CursorEntered,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(CursorEnteredEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::CursorLeft { .. } => {
                    let base = TaoEvent {
                        kind: EventKind::CursorLeft,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(CursorLeftEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Started => {
                    let base = TaoEvent {
                        kind: EventKind::Started,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(StartedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Suspended => {
                    let base = TaoEvent {
                        kind: EventKind::Suspended,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(SuspendedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Resumed => {
                    let base = TaoEvent {
                        kind: EventKind::Resumed,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(ResumedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Stopped => {
                    let base = TaoEvent {
                        kind: EventKind::Stopped,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(StoppedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::ReceivedImeText(text) => {
                    let base = TaoEvent {
                        kind: EventKind::ReceivedImeText,
                        window_id: Some(wid),
                    };
                    let init =
                        PyClassInitializer::from(base).add_subclass(ReceivedImeTextEvent {
                            text: text.clone(),
                        });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::TouchpadPressure {
                    pressure, stage, ..
                } => {
                    let base = TaoEvent {
                        kind: EventKind::TouchpadPressure,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(TouchpadPressureEvent {
                        pressure: *pressure as f64,
                        stage: *stage,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::AxisMotion { axis, value, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::AxisMotion,
                        window_id: Some(wid),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(AxisMotionEvent {
                        axis: *axis,
                        value: *value,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::Touch(touch) => {
                    let base = TaoEvent {
                        kind: EventKind::Touch,
                        window_id: Some(wid),
                    };
                    let force = match touch.force {
                        Some(tao::event::Force::Normalized(f)) => Some(f),
                        Some(tao::event::Force::Calibrated { force, .. }) => Some(force),
                        _ => None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(TouchEvent {
                        phase: TouchPhase::from(touch.phase),
                        x: touch.location.x,
                        y: touch.location.y,
                        force,
                        id: touch.id,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                WindowEvent::DecorationsClick => {
                    let base = TaoEvent {
                        kind: EventKind::DecorationsClick,
                        window_id: Some(wid),
                    };
                    let init =
                        PyClassInitializer::from(base).add_subclass(DecorationsClickEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                _ => None,
            }
        }
        Event::NewEvents(cause) => {
            let base = TaoEvent {
                kind: EventKind::NewEvents,
                window_id: None,
            };
            let init = PyClassInitializer::from(base).add_subclass(NewEventsEvent {
                cause: StartCause::from(*cause),
            });
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::MainEventsCleared => {
            let base = TaoEvent {
                kind: EventKind::MainEventsCleared,
                window_id: None,
            };
            let init = PyClassInitializer::from(base).add_subclass(MainEventsClearedEvent {});
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::RedrawEventsCleared => {
            let base = TaoEvent {
                kind: EventKind::RedrawEventsCleared,
                window_id: None,
            };
            let init = PyClassInitializer::from(base).add_subclass(RedrawEventsClearedEvent {});
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::Opened { urls } => {
            let base = TaoEvent {
                kind: EventKind::Opened,
                window_id: None,
            };
            let init = PyClassInitializer::from(base).add_subclass(OpenedEvent {
                urls: urls.iter().map(|u| u.to_string()).collect(),
            });
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::DeviceEvent {
            event: device_event,
            ..
        } => match device_event {
                tao::event::DeviceEvent::Added => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceAdded,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceAddedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::Removed => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceRemoved,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceRemovedEvent {});
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::MouseMotion { delta, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceMouseMotion,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceMouseMotionEvent {
                        dx: delta.0,
                        dy: delta.1,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::MouseWheel { delta, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceMouseWheel,
                        window_id: None,
                    };
                    let (kind, dx, dy) = match delta {
                        tao::event::MouseScrollDelta::LineDelta(x, y) => {
                            (ScrollDeltaKind::Line, *x as f64, *y as f64)
                        }
                        tao::event::MouseScrollDelta::PixelDelta(pos) => {
                            (ScrollDeltaKind::Pixel, pos.x, pos.y)
                        }
                        _ => (ScrollDeltaKind::Line, 0.0, 0.0),
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceMouseWheelEvent {
                        delta_kind: kind,
                        dx,
                        dy,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::Motion { axis, value, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceMotion,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceMotionEvent {
                        axis: *axis,
                        value: *value,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::Button { button, state, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceButton,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceButtonEvent {
                        button: *button,
                        state: ElementState::from(*state),
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::Key(key_event) => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceKey,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceKeyEvent {
                        physical_key: key_event.physical_key.to_string(),
                        state: ElementState::from(key_event.state),
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                tao::event::DeviceEvent::Text { codepoint, .. } => {
                    let base = TaoEvent {
                        kind: EventKind::DeviceText,
                        window_id: None,
                    };
                    let init = PyClassInitializer::from(base).add_subclass(DeviceTextEvent {
                        codepoint: *codepoint as u32,
                    });
                    Py::new(py, init).ok().map(|p| p.into_any())
                }
                _ => None,
            }
        Event::RedrawRequested(window_id) => {
            let wid = wid_to_u64(window_id);
            let base = TaoEvent {
                kind: EventKind::RedrawRequested,
                window_id: Some(wid),
            };
            let init = PyClassInitializer::from(base).add_subclass(RedrawRequestedEvent {});
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::UserEvent(data) => {
            let base = TaoEvent {
                kind: EventKind::UserEvent,
                window_id: None,
            };
            let init =
                PyClassInitializer::from(base).add_subclass(UserEvent { data: data.clone() });
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::LoopDestroyed => {
            let base = TaoEvent {
                kind: EventKind::LoopDestroyed,
                window_id: None,
            };
            let init = PyClassInitializer::from(base).add_subclass(LoopDestroyedEvent {});
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        Event::Reopen {
            has_visible_windows,
            ..
        } => {
            let base = TaoEvent {
                kind: EventKind::Reopen,
                window_id: None,
            };
            let init = PyClassInitializer::from(base).add_subclass(ReopenEvent {
                has_visible_windows: *has_visible_windows,
            });
            Py::new(py, init).ok().map(|p| p.into_any())
        }
        _ => None,
    }
}

// Key code parsing

/// Parse a key-code name (e.g. ``"KeyW"``, ``"Space"``, ``"A"``) into
/// its canonical form (``"KeyW"``), or ``None`` if unknown.
///
/// Accepts both the canonical event spelling (``"KeyW"``, what
/// :attr:`KeyboardInputEvent.physical_key` carries) and tao's bare
/// accelerator names (``"W"``, ``"SPACE"``). Case-insensitive.
/// Useful for matching against a normalized constant::
///
///     if parse_key_code(event.physical_key) == parse_key_code("KeyW"):
///         ...
#[pyfunction]
pub fn parse_key_code(text: &str) -> Option<String> {
    // tao's FromStr knows bare names ("W", "SPACE") but not the
    // "Key"-prefixed Display spelling — strip it for parsing.
    let bare = text.strip_prefix("Key").unwrap_or(text);
    match bare.parse::<tao::keyboard::KeyCode>() {
        // Unknown input parses as Unidentified instead of failing —
        // treat that as "no match" and return None.
        Ok(tao::keyboard::KeyCode::Unidentified(
            tao::keyboard::NativeKeyCode::Unidentified,
        )) => None,
        Ok(key) => Some(key.to_string()),
        Err(_) => None,
    }
}
