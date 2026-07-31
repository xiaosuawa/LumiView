use std::hash::{Hash, Hasher};

use pyo3::prelude::*;
use tao::event::{Event, WindowEvent};
use tao::window::WindowId;

use crate::types::{
    ElementState, EventKind, KeyLocation, ModifiersState, MouseButton, ScrollDeltaKind, Theme,
    TouchPhase,
};

// ── WindowId → u64 ──────────────────────────────────────────────────────

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

// ── TaoEvent (base) ─────────────────────────────────────────────────────

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

// ── Event subclass boilerplate ──────────────────────────────────────────

macro_rules! empty_event {
    ($name:ident, $doc:expr) => {
        #[doc = $doc]
        #[pyclass(extends = TaoEvent)]
        pub struct $name {}

        #[pymethods]
        impl $name {}
    };
}

// ── Geometry events ─────────────────────────────────────────────────────

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

// ── Lifecycle events ────────────────────────────────────────────────────

empty_event!(
    CloseRequestedEvent,
    "User clicked the close button or pressed Alt+F4."
);
empty_event!(DestroyedEvent, "Window has been fully destroyed.");
empty_event!(FocusedEvent, "Window gained keyboard focus.");
empty_event!(UnfocusedEvent, "Window lost keyboard focus.");

/// DPI scale factor changed.
#[pyclass(extends = TaoEvent)]
pub struct ScaleFactorChangedEvent {
    #[pyo3(get)]
    pub scale_factor: f64,
    #[pyo3(get)]
    pub new_scale_factor: f64,
}

#[pymethods]
impl ScaleFactorChangedEvent {
    fn __repr__(&self) -> String {
        format!("ScaleFactorChangedEvent(sf={})", self.new_scale_factor)
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

// ── Input events ────────────────────────────────────────────────────────

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

// ── Cursor boundary events ──────────────────────────────────────────────

empty_event!(CursorEnteredEvent, "Cursor entered the window.");
empty_event!(CursorLeftEvent, "Cursor left the window.");

// ── Redraw event ────────────────────────────────────────────────────────

empty_event!(
    RedrawRequestedEvent,
    "The system has requested a window redraw."
);

// ── User event ──────────────────────────────────────────────────────────

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

// ── Loop destroyed ──────────────────────────────────────────────────────

empty_event!(
    LoopDestroyedEvent,
    "Sent once after the event loop has exited."
);

// ── build_event — type-driven factory ───────────────────────────────────

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
                            new_scale_factor: *scale_factor,
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
                        physical_key: format!("{:?}", key_event.physical_key),
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
                _ => None,
            }
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
        _ => None,
    }
}
