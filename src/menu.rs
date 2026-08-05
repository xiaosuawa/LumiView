use std::sync::OnceLock;

use pyo3::prelude::*;

use muda::accelerator::Accelerator;
use muda::{IsMenuItem, MenuEvent, MenuId};

// MENU_EVENT_CALLBACK — global menu-event bridge
//
// muda's MenuEvent::set_event_handler stores the handler in a OnceCell and
// can only be set once per process (later calls are silently ignored), so
// the Python callback is registered here exactly once by App.run() in its
// STARTING phase. All menu activation events — app menus (macOS), window
// menu bars (Windows) and tray icon menus (all platforms) — funnel through
// this single handler.
//
// Threading: menu events fire on the main thread only (WM_COMMAND via
// window subclass on Windows, NSMenu action on macOS, GTK activate on
// Linux). The main thread releases the GIL while the tao loop runs
// (run_event_loop_detached's py.detach), so Python::with_gil here can
// never deadlock.

static MENU_EVENT_CALLBACK: OnceLock<Py<PyAny>> = OnceLock::new();

/// Register the Python callback that receives every menu activation.
/// Called once by ``App.run()``; idempotent (later calls are no-ops).
#[pyfunction]
pub fn init_menu_events(callback: Py<PyAny>) -> PyResult<()> {
    if MENU_EVENT_CALLBACK.set(callback).is_err() {
        return Ok(());
    }
    MenuEvent::set_event_handler(Some(move |event: MenuEvent| {
        Python::attach(|py| {
            if let Some(cb) = MENU_EVENT_CALLBACK.get() {
                let ev = match Py::new(py, MenuItemActivatedEvent { id: event.id.0.clone() }) {
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

// MenuItemActivatedEvent

/// A menu item was activated (app menu, window menu bar, or tray menu).
///
/// Lightweight and thread-safe: the dispatcher resolves the id against the
/// registered menu item wrappers and fills in the Python-side event.
#[pyclass]
pub struct MenuItemActivatedEvent {
    /// The item's id string (as passed at construction).
    #[pyo3(get)]
    pub id: String,
}

#[pymethods]
impl MenuItemActivatedEvent {
    fn __repr__(&self) -> String {
        format!("MenuItemActivatedEvent(id={:?})", self.id)
    }
}

// parse_accelerator

/// Parse a muda accelerator string (``"CmdOrCtrl+Shift+K"``) into an
/// ``Option<Accelerator>``. ``None`` maps to ``Ok(None)``; a parse failure
/// surfaces as ``ValueError`` so callers cannot silently lose a shortcut.
fn parse_accelerator(raw: Option<&str>) -> PyResult<Option<Accelerator>> {
    match raw {
        None => Ok(None),
        Some(s) => Accelerator::try_from(s)
            .map(Some)
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "invalid accelerator {s:?}: {e}"
                ))
            }),
    }
}

// TaoMenuItem

/// A plain menu item. Unsendable — created and used on the main thread.
#[pyclass(unsendable, weakref)]
pub struct TaoMenuItem {
    pub(crate) inner: muda::MenuItem,
}

#[pymethods]
impl TaoMenuItem {
    /// Create a menu item. *accelerator* uses muda syntax
    /// (``"CmdOrCtrl+Shift+K"``); a malformed string raises ``ValueError``.
    #[new]
    fn new(id: String, text: String, enabled: bool, accelerator: Option<String>) -> PyResult<Self> {
        let accel = parse_accelerator(accelerator.as_deref())?;
        Ok(Self {
            inner: muda::MenuItem::with_id(MenuId::from(id), text, enabled, accel),
        })
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id().0.clone()
    }

    fn set_text(&self, text: String) {
        self.inner.set_text(text);
    }

    fn set_enabled(&self, enabled: bool) {
        self.inner.set_enabled(enabled);
    }

    fn is_enabled(&self) -> bool {
        self.inner.is_enabled()
    }

    /// Replace the accelerator (``None`` removes it).
    fn set_accelerator(&self, accelerator: Option<String>) -> PyResult<()> {
        let accel = parse_accelerator(accelerator.as_deref())?;
        self.inner
            .set_accelerator(accel)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn __repr__(&self) -> String {
        format!("TaoMenuItem(id={:?})", self.inner.id().0)
    }
}

// TaoCheckMenuItem

/// A checkable menu item (toggle with a checkmark).
#[pyclass(unsendable, weakref)]
pub struct TaoCheckMenuItem {
    pub(crate) inner: muda::CheckMenuItem,
}

#[pymethods]
impl TaoCheckMenuItem {
    #[new]
    fn new(
        id: String,
        text: String,
        enabled: bool,
        checked: bool,
        accelerator: Option<String>,
    ) -> PyResult<Self> {
        let accel = parse_accelerator(accelerator.as_deref())?;
        Ok(Self {
            inner: muda::CheckMenuItem::with_id(MenuId::from(id), text, enabled, checked, accel),
        })
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id().0.clone()
    }

    fn set_text(&self, text: String) {
        self.inner.set_text(text);
    }

    fn set_enabled(&self, enabled: bool) {
        self.inner.set_enabled(enabled);
    }

    fn is_enabled(&self) -> bool {
        self.inner.is_enabled()
    }

    fn set_checked(&self, checked: bool) {
        self.inner.set_checked(checked);
    }

    fn is_checked(&self) -> bool {
        self.inner.is_checked()
    }

    fn set_accelerator(&self, accelerator: Option<String>) -> PyResult<()> {
        let accel = parse_accelerator(accelerator.as_deref())?;
        self.inner
            .set_accelerator(accel)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn __repr__(&self) -> String {
        format!("TaoCheckMenuItem(id={:?})", self.inner.id().0)
    }
}

// TaoSubmenu

/// A submenu: a menu item that contains other items.
#[pyclass(unsendable, weakref)]
pub struct TaoSubmenu {
    pub(crate) inner: muda::Submenu,
}

#[pymethods]
impl TaoSubmenu {
    #[new]
    fn new(id: String, text: String, enabled: bool) -> Self {
        Self {
            inner: muda::Submenu::with_id(MenuId::from(id), text, enabled),
        }
    }

    #[getter]
    fn id(&self) -> String {
        self.inner.id().0.clone()
    }

    fn set_text(&self, text: String) {
        self.inner.set_text(text);
    }

    fn set_enabled(&self, enabled: bool) {
        self.inner.set_enabled(enabled);
    }

    fn is_enabled(&self) -> bool {
        self.inner.is_enabled()
    }

    fn append(&self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .append(item.item())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn prepend(&self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .prepend(item.item())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn insert(&self, item: &Bound<'_, PyAny>, position: usize) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .insert(item.item(), position)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn remove(&self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .remove(item.item())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// macOS: register this submenu as the app's "Window" menu (window list
    /// and tiling shortcuts).
    #[cfg(target_os = "macos")]
    fn set_as_windows_menu_for_nsapp(&self) {
        self.inner.set_as_windows_menu_for_nsapp();
    }

    /// macOS: register this submenu as the app's Help menu.
    #[cfg(target_os = "macos")]
    fn set_as_help_menu_for_nsapp(&self) {
        self.inner.set_as_help_menu_for_nsapp();
    }

    fn __repr__(&self) -> String {
        format!("TaoSubmenu(id={:?})", self.inner.id().0)
    }
}

// TaoPredefinedMenuItem

/// A system-behavior menu item (copy, quit, separator, ...).
///
/// Predefined items perform their OS action natively and **do not**
/// generate activation events. *kind* selects the system behavior;
/// *text* overrides the system-provided label; *name*/*version* feed the
/// "About" dialog only.
#[pyclass(unsendable, weakref)]
pub struct TaoPredefinedMenuItem {
    pub(crate) inner: muda::PredefinedMenuItem,
}

fn predefined(
    kind: &str,
    text: Option<&str>,
    name: Option<String>,
    version: Option<String>,
) -> PyResult<muda::PredefinedMenuItem> {
    let item = match kind {
        "separator" => muda::PredefinedMenuItem::separator(),
        "copy" => muda::PredefinedMenuItem::copy(text),
        "cut" => muda::PredefinedMenuItem::cut(text),
        "paste" => muda::PredefinedMenuItem::paste(text),
        "select_all" => muda::PredefinedMenuItem::select_all(text),
        "undo" => muda::PredefinedMenuItem::undo(text),
        "redo" => muda::PredefinedMenuItem::redo(text),
        "minimize" => muda::PredefinedMenuItem::minimize(text),
        "maximize" => muda::PredefinedMenuItem::maximize(text),
        "fullscreen" => muda::PredefinedMenuItem::fullscreen(text),
        "hide" => muda::PredefinedMenuItem::hide(text),
        "hide_others" => muda::PredefinedMenuItem::hide_others(text),
        "show_all" => muda::PredefinedMenuItem::show_all(text),
        "close_window" => muda::PredefinedMenuItem::close_window(text),
        "quit" => muda::PredefinedMenuItem::quit(text),
        "about" => muda::PredefinedMenuItem::about(
            text,
            Some(muda::AboutMetadata {
                name,
                version,
                ..Default::default()
            }),
        ),
        "services" => muda::PredefinedMenuItem::services(text),
        "bring_all_to_front" => muda::PredefinedMenuItem::bring_all_to_front(text),
        other => {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "unknown predefined menu kind {other:?}"
            )))
        }
    };
    Ok(item)
}

#[pymethods]
impl TaoPredefinedMenuItem {
    #[new]
    fn new(
        kind: String,
        text: Option<String>,
        name: Option<String>,
        version: Option<String>,
    ) -> PyResult<Self> {
        Ok(Self {
            inner: predefined(&kind, text.as_deref(), name, version)?,
        })
    }

    fn __repr__(&self) -> String {
        "TaoPredefinedMenuItem()".into()
    }
}

// TaoMenu

/// A root menu — the menu bar (macOS app menu / Windows window menu) or
/// the context menu attached to a tray icon. Can be attached to at most
/// one place at a time; one Menu may be attached to several windows.
#[pyclass(unsendable, weakref)]
pub struct TaoMenu {
    pub(crate) inner: muda::Menu,
}

#[pymethods]
impl TaoMenu {
    /// Create an empty root menu. Requires a running app — menus need the
    /// event loop to deliver activation events.
    #[new]
    fn new() -> PyResult<Self> {
        if !crate::event_loop::loop_running() {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "Menus require a running app — create them inside run()/ReadyEvent handlers",
            ));
        }
        Ok(Self {
            inner: muda::Menu::new(),
        })
    }

    fn append(&self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .append(item.item())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn append_items(&self, items: Vec<Bound<'_, PyAny>>) -> PyResult<()> {
        let refs: Vec<ItemRef<'_>> = items.iter().map(extract_item).collect::<PyResult<_>>()?;
        let dyn_items: Vec<&dyn IsMenuItem> = refs.iter().map(ItemRef::item).collect();
        self.inner
            .append_items(&dyn_items)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn prepend(&self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .prepend(item.item())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn insert(&self, item: &Bound<'_, PyAny>, position: usize) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .insert(item.item(), position)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn remove(&self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        let item = extract_item(item)?;
        self.inner
            .remove(item.item())
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// macOS: install this menu as the application menu bar (replaces the
    /// current one). Call from the main thread.
    #[cfg(target_os = "macos")]
    fn init_for_nsapp(&self) {
        self.inner.init_for_nsapp();
    }

    /// macOS: remove this menu from the application menu bar.
    #[cfg(target_os = "macos")]
    fn remove_for_nsapp(&self) {
        self.inner.remove_for_nsapp();
    }

    /// Windows: attach this menu as the menu bar of the given window
    /// (``hwnd`` comes from ``TaoWindow.native_handle()``).
    ///
    /// # Safety
    ///
    /// ``hwnd`` must belong to a live window and be accessed from the
    /// main thread — the PyO3 unsendable guard on TaoMenu ensures the
    /// call site is the main thread.
    #[cfg(target_os = "windows")]
    fn init_for_hwnd(&self, hwnd: isize) -> PyResult<()> {
        unsafe { self.inner.init_for_hwnd(hwnd) }
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    /// Windows: detach this menu from the given window's menu bar.
    #[cfg(target_os = "windows")]
    fn remove_for_hwnd(&self, hwnd: isize) -> PyResult<()> {
        unsafe { self.inner.remove_for_hwnd(hwnd) }
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))
    }

    fn __repr__(&self) -> String {
        "TaoMenu()".into()
    }
}

// ItemRef — unified downcast entry point
//
// muda's MenuItemKind does not implement IsMenuItem (only the concrete
// types do), so every append/insert/remove goes through this enum.

enum ItemRef<'a> {
    MenuItem(PyRef<'a, TaoMenuItem>),
    Submenu(PyRef<'a, TaoSubmenu>),
    Check(PyRef<'a, TaoCheckMenuItem>),
    Predefined(PyRef<'a, TaoPredefinedMenuItem>),
}

impl ItemRef<'_> {
    fn item(&self) -> &dyn IsMenuItem {
        match self {
            ItemRef::MenuItem(i) => &i.inner,
            ItemRef::Submenu(s) => &s.inner,
            ItemRef::Check(c) => &c.inner,
            ItemRef::Predefined(p) => &p.inner,
        }
    }
}

fn extract_item<'a>(obj: &'a Bound<'_, PyAny>) -> PyResult<ItemRef<'a>> {
    if let Ok(r) = obj.extract::<PyRef<'_, TaoMenuItem>>() {
        return Ok(ItemRef::MenuItem(r));
    }
    if let Ok(r) = obj.extract::<PyRef<'_, TaoSubmenu>>() {
        return Ok(ItemRef::Submenu(r));
    }
    if let Ok(r) = obj.extract::<PyRef<'_, TaoCheckMenuItem>>() {
        return Ok(ItemRef::Check(r));
    }
    if let Ok(r) = obj.extract::<PyRef<'_, TaoPredefinedMenuItem>>() {
        return Ok(ItemRef::Predefined(r));
    }
    Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
        "expected TaoMenuItem, TaoSubmenu, TaoCheckMenuItem or TaoPredefinedMenuItem",
    ))
}
