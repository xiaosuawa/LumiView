use std::sync::OnceLock;

use pyo3::prelude::*;
use tray_icon::{Icon, TrayIconEvent};

use crate::menu::TaoMenu;
use crate::types::{ElementState, MouseButton};

// TRAY_EVENT_CALLBACK — global tray-event bridge
//
// tray-icon's TrayIconEvent::set_event_handler uses the same OnceCell
// pattern as muda: it can be set once per process. Registered by
// App.run() in its STARTING phase. Tray events fire on the main thread
// (the hidden window's message loop on Windows, NSStatusItem on macOS);
// the GIL is released while the tao loop runs, so with_gil cannot deadlock.

static TRAY_EVENT_CALLBACK: OnceLock<Py<PyAny>> = OnceLock::new();

/// Register the Python callback that receives every tray icon event.
/// Called once by ``App.run()``; idempotent (later calls are no-ops).
#[pyfunction]
pub fn init_tray_events(callback: Py<PyAny>) -> PyResult<()> {
    if TRAY_EVENT_CALLBACK.set(callback).is_err() {
        return Ok(());
    }
    TrayIconEvent::set_event_handler(Some(move |event| {
        Python::attach(|py| {
            if let Some(cb) = TRAY_EVENT_CALLBACK.get() {
                let ev = match build_tray_event(py, event) {
                    Ok(ev) => ev,
                    Err(e) => {
                        e.write_unraisable(py, None);
                        return;
                    }
                };
                if let Err(e) = cb.call1(py, (ev,)) {
                    e.write_unraisable(py, None);
                }
            }
        });
    }));
    Ok(())
}

// Tray events — plain pyclasses, safe to hand across threads

/// The tray icon rect (physical): ``(x, y, width, height)``.
type RectTuple = (f64, f64, f64, f64);

fn rect_tuple(rect: &tray_icon::Rect) -> RectTuple {
    (
        rect.position.x,
        rect.position.y,
        rect.size.width as f64,
        rect.size.height as f64,
    )
}

/// A click on a tray icon.
#[pyclass]
pub struct TrayIconClickEvent {
    /// The tray icon id.
    #[pyo3(get)]
    pub id: String,
    /// Physical pointer position ``(x, y)``.
    #[pyo3(get)]
    pub position: (f64, f64),
    /// Physical tray icon bounds ``(x, y, width, height)``.
    #[pyo3(get)]
    pub rect: RectTuple,
    /// The mouse button that triggered the click.
    #[pyo3(get)]
    pub button: MouseButton,
    /// Pressed or released.
    #[pyo3(get)]
    pub button_state: ElementState,
}

#[pymethods]
impl TrayIconClickEvent {
    fn __repr__(&self) -> String {
        format!(
            "TrayIconClickEvent(id={:?}, position={:?}, button={:?}, button_state={:?})",
            self.id, self.position, self.button, self.button_state
        )
    }
}

/// A double click on a tray icon (Windows only).
#[pyclass]
pub struct TrayIconDoubleClickEvent {
    /// The tray icon id.
    #[pyo3(get)]
    pub id: String,
    /// Physical pointer position ``(x, y)``.
    #[pyo3(get)]
    pub position: (f64, f64),
    /// Physical tray icon bounds ``(x, y, width, height)``.
    #[pyo3(get)]
    pub rect: RectTuple,
    /// The mouse button that triggered the click.
    #[pyo3(get)]
    pub button: MouseButton,
}

#[pymethods]
impl TrayIconDoubleClickEvent {
    fn __repr__(&self) -> String {
        format!(
            "TrayIconDoubleClickEvent(id={:?}, position={:?}, button={:?})",
            self.id, self.position, self.button
        )
    }
}

/// The pointer entered the tray icon region.
#[pyclass]
pub struct TrayIconEnterEvent {
    /// The tray icon id.
    #[pyo3(get)]
    pub id: String,
    /// Physical pointer position ``(x, y)``.
    #[pyo3(get)]
    pub position: (f64, f64),
    /// Physical tray icon bounds ``(x, y, width, height)``.
    #[pyo3(get)]
    pub rect: RectTuple,
}

#[pymethods]
impl TrayIconEnterEvent {
    fn __repr__(&self) -> String {
        format!("TrayIconEnterEvent(id={:?}, position={:?})", self.id, self.position)
    }
}

/// The pointer moved over the tray icon region.
#[pyclass]
pub struct TrayIconMoveEvent {
    /// The tray icon id.
    #[pyo3(get)]
    pub id: String,
    /// Physical pointer position ``(x, y)``.
    #[pyo3(get)]
    pub position: (f64, f64),
    /// Physical tray icon bounds ``(x, y, width, height)``.
    #[pyo3(get)]
    pub rect: RectTuple,
}

#[pymethods]
impl TrayIconMoveEvent {
    fn __repr__(&self) -> String {
        format!("TrayIconMoveEvent(id={:?}, position={:?})", self.id, self.position)
    }
}

/// The pointer left the tray icon region.
#[pyclass]
pub struct TrayIconLeaveEvent {
    /// The tray icon id.
    #[pyo3(get)]
    pub id: String,
    /// Physical pointer position ``(x, y)``.
    #[pyo3(get)]
    pub position: (f64, f64),
    /// Physical tray icon bounds ``(x, y, width, height)``.
    #[pyo3(get)]
    pub rect: RectTuple,
}

#[pymethods]
impl TrayIconLeaveEvent {
    fn __repr__(&self) -> String {
        format!("TrayIconLeaveEvent(id={:?}, position={:?})", self.id, self.position)
    }
}

fn build_tray_event(py: Python<'_>, event: TrayIconEvent) -> PyResult<Py<PyAny>> {
    let ev: Py<PyAny> = match event {
        TrayIconEvent::Click {
            id,
            position,
            rect,
            button,
            button_state,
        } => Py::new(
            py,
            TrayIconClickEvent {
                id: id.0.clone(),
                position: (position.x, position.y),
                rect: rect_tuple(&rect),
                button: MouseButton::from(button),
                button_state: ElementState::from(button_state),
            },
        )?.into(),
        TrayIconEvent::DoubleClick {
            id,
            position,
            rect,
            button,
        } => Py::new(
            py,
            TrayIconDoubleClickEvent {
                id: id.0.clone(),
                position: (position.x, position.y),
                rect: rect_tuple(&rect),
                button: MouseButton::from(button),
            },
        )?.into(),
        TrayIconEvent::Enter {
            id,
            position,
            rect,
        } => Py::new(
            py,
            TrayIconEnterEvent {
                id: id.0.clone(),
                position: (position.x, position.y),
                rect: rect_tuple(&rect),
            },
        )?.into(),
        TrayIconEvent::Move {
            id,
            position,
            rect,
        } => Py::new(
            py,
            TrayIconMoveEvent {
                id: id.0.clone(),
                position: (position.x, position.y),
                rect: rect_tuple(&rect),
            },
        )?.into(),
        TrayIconEvent::Leave {
            id,
            position,
            rect,
        } => Py::new(
            py,
            TrayIconLeaveEvent {
                id: id.0.clone(),
                position: (position.x, position.y),
                rect: rect_tuple(&rect),
            },
        )?.into(),
        // TrayIconEvent is non-exhaustive (platform-specific variants may
        // be added) — surface unknown events as errors instead of dropping.
        _ => {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "unknown tray icon event",
            ))
        }
    };
    Ok(ev)
}

// TaoTrayIcon

/// A system tray icon. Unsendable — created and dropped on the main
/// thread; dropping the object removes the icon (the platform handle is
/// torn down in ``Drop``).
#[pyclass(unsendable)]
pub struct TaoTrayIcon {
    inner: tray_icon::TrayIcon,
}

#[pymethods]
impl TaoTrayIcon {
    /// Create a tray icon. *icon* is raw RGBA bytes with the given
    /// width/height; *menu* is a :class:`TaoMenu` whose activation events
    /// flow through the shared menu-event callback.
    #[new]
    fn new(
        id: String,
        icon: &[u8],
        icon_width: u32,
        icon_height: u32,
        tooltip: Option<String>,
        menu: Option<PyRef<'_, TaoMenu>>,
        menu_on_left_click: bool,
        menu_on_right_click: bool,
    ) -> PyResult<Self> {
        if !crate::event_loop::loop_running() {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "Tray icons require a running app — create them inside run()/ReadyEvent handlers",
            ));
        }
        let icon = Icon::from_rgba(icon.to_vec(), icon_width, icon_height).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid tray icon: {e}"))
        })?;
        let mut builder = tray_icon::TrayIconBuilder::new()
            .with_id(id)
            .with_icon(icon)
            .with_menu_on_left_click(menu_on_left_click)
            .with_menu_on_right_click(menu_on_right_click);
        if let Some(tooltip) = tooltip {
            builder = builder.with_tooltip(tooltip);
        }
        if let Some(menu) = menu {
            builder = builder.with_menu(Box::new(menu.inner.clone()));
        }
        let inner = builder
            .build()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
        Ok(Self { inner })
    }

    /// The tray icon id (as passed at construction).
    #[getter]
    fn id(&self) -> String {
        self.inner.id().0.clone()
    }

    /// Replace the icon (raw RGBA bytes).
    fn set_icon(&self, icon: &[u8], width: u32, height: u32) -> PyResult<()> {
        let icon = Icon::from_rgba(icon.to_vec(), width, height).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid tray icon: {e}"))
        })?;
        self.inner
            .set_icon(Some(icon))
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// Replace the tooltip (``None`` removes it).
    fn set_tooltip(&self, tooltip: Option<String>) -> PyResult<()> {
        self.inner
            .set_tooltip(tooltip)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// Show or hide the icon.
    fn set_visible(&self, visible: bool) -> PyResult<()> {
        self.inner
            .set_visible(visible)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// Open the attached menu at the icon's position.
    fn show_menu(&self) {
        self.inner.show_menu();
    }

    /// macOS: render the icon as a template image (auto black/white).
    fn set_icon_as_template(&self, is_template: bool) {
        self.inner.set_icon_as_template(is_template);
    }

    /// Show the attached menu on left click.
    fn set_show_menu_on_left_click(&self, enable: bool) {
        self.inner.set_show_menu_on_left_click(enable);
    }

    /// Show the attached menu on right click.
    fn set_show_menu_on_right_click(&self, enable: bool) {
        self.inner.set_show_menu_on_right_click(enable);
    }

    fn __repr__(&self) -> String {
        format!("TaoTrayIcon(id={:?})", self.inner.id().0)
    }
}
