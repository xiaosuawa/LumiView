#[cfg(target_os = "windows")]
use std::cell::RefCell;
use std::hash::{Hash, Hasher};
use std::sync::Arc;

use pyo3::exceptions::{PyNotImplementedError, PyRuntimeError};
use pyo3::prelude::*;
use tao::dpi::{LogicalPosition, LogicalSize};
use tao::window::{Window, WindowBuilder};
use window_vibrancy::{NSVisualEffectMaterial, NSVisualEffectState};

use crate::types::{ResizeDirection, WindowEffect, WindowHandleKind};

fn effect_error(error: window_vibrancy::Error) -> PyErr {
    match error {
        window_vibrancy::Error::UnsupportedPlatform(_)
        | window_vibrancy::Error::UnsupportedPlatformVersion(_) => {
            PyNotImplementedError::new_err(error.to_string())
        }
        _ => PyRuntimeError::new_err(error.to_string()),
    }
}

fn interaction_error(error: tao::error::ExternalError) -> PyErr {
    match error {
        tao::error::ExternalError::NotSupported(_) => {
            PyNotImplementedError::new_err(error.to_string())
        }
        _ => PyRuntimeError::new_err(error.to_string()),
    }
}

// ── TaoWindowBuilder ──────────────────────────────────────────────────────

/// Configure a window before creation.
///
/// All methods mutate the builder in-place (no chaining).  Call
/// :meth:`build` once to create the :class:`TaoWindow`.
///
/// Example::
///
///     builder = TaoWindowBuilder()
///     builder.with_title("My Window")
///     builder.with_inner_size(800, 600)
///     window = builder.build(event_loop)
#[pyclass(unsendable)]
pub struct TaoWindowBuilder {
    builder: WindowBuilder,
    #[cfg(target_os = "windows")]
    transparent: bool,
}

#[pymethods]
impl TaoWindowBuilder {
    #[new]
    fn new() -> Self {
        TaoWindowBuilder {
            builder: WindowBuilder::new(),
            #[cfg(target_os = "windows")]
            transparent: false,
        }
    }

    fn with_title(&mut self, title: &str) {
        self.builder = self.builder.clone().with_title(title);
    }

    fn with_inner_size(&mut self, width: f64, height: f64) {
        self.builder = self
            .builder
            .clone()
            .with_inner_size(LogicalSize::new(width, height));
    }

    fn with_min_inner_size(&mut self, width: f64, height: f64) {
        self.builder = self
            .builder
            .clone()
            .with_min_inner_size(LogicalSize::new(width, height));
    }

    fn with_max_inner_size(&mut self, width: f64, height: f64) {
        self.builder = self
            .builder
            .clone()
            .with_max_inner_size(LogicalSize::new(width, height));
    }

    fn with_position(&mut self, x: f64, y: f64) {
        self.builder = self
            .builder
            .clone()
            .with_position(LogicalPosition::new(x, y));
    }

    fn with_resizable(&mut self, resizable: bool) {
        self.builder = self.builder.clone().with_resizable(resizable);
    }

    fn with_minimizable(&mut self, minimizable: bool) {
        self.builder = self.builder.clone().with_minimizable(minimizable);
    }

    fn with_maximizable(&mut self, maximizable: bool) {
        self.builder = self.builder.clone().with_maximizable(maximizable);
    }

    fn with_closable(&mut self, closable: bool) {
        self.builder = self.builder.clone().with_closable(closable);
    }

    fn with_maximized(&mut self, maximized: bool) {
        self.builder = self.builder.clone().with_maximized(maximized);
    }

    fn with_visible(&mut self, visible: bool) {
        self.builder = self.builder.clone().with_visible(visible);
    }

    fn with_transparent(&mut self, transparent: bool) {
        #[cfg(target_os = "windows")]
        {
            self.transparent = transparent;
        }
        self.builder = self.builder.clone().with_transparent(transparent);
    }

    fn with_decorations(&mut self, decorations: bool) {
        self.builder = self.builder.clone().with_decorations(decorations);
    }

    /// Enable or disable Tao's native shadow for an undecorated Windows window.
    ///
    /// Transparent custom-chrome windows generally want this disabled because
    /// DWM's hidden non-client border can leave a stale edge while resizing.
    fn with_undecorated_shadow(&mut self, shadow: bool) {
        #[cfg(target_os = "windows")]
        {
            use tao::platform::windows::WindowBuilderExtWindows;
            self.builder = self.builder.clone().with_undecorated_shadow(shadow);
        }
        #[cfg(not(target_os = "windows"))]
        let _ = shadow;
    }

    fn with_always_on_top(&mut self, always: bool) {
        self.builder = self.builder.clone().with_always_on_top(always);
    }

    fn with_focused(&mut self, focused: bool) {
        self.builder = self.builder.clone().with_focused(focused);
    }

    fn with_focusable(&mut self, focusable: bool) {
        self.builder = self.builder.clone().with_focusable(focusable);
    }

    fn with_content_protection(&mut self, protected: bool) {
        self.builder = self.builder.clone().with_content_protection(protected);
    }

    fn with_visible_on_all_workspaces(&mut self, visible: bool) {
        self.builder = self.builder.clone().with_visible_on_all_workspaces(visible);
    }

    /// Set the window icon from raw RGBA pixel data.
    ///
    /// *width* × *height* pixels, each pixel 4 bytes (R, G, B, A).
    /// The total length of *rgba* must be ``width * height * 4``.
    fn with_window_icon(&mut self, width: u32, height: u32, rgba: Vec<u8>) -> PyResult<()> {
        let icon = tao::window::Icon::from_rgba(rgba, width, height).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid icon: {e}"))
        })?;
        self.builder = self.builder.clone().with_window_icon(Some(icon));
        Ok(())
    }

    /// Create the ``TaoWindow``.
    ///
    /// Works both before and during ``el.run()`` — the underlying
    /// ``EventLoopWindowTarget`` pointer is captured at construction
    /// time via a thread-local, so no event-loop reference is needed.
    fn build(&self) -> PyResult<TaoWindow> {
        let elwt = crate::event_loop::event_loop_target().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("EventLoop not available")
        })?;
        let window = Arc::new(
            self.builder
                .clone()
                .build(elwt)
                .map_err(|e| PyRuntimeError::new_err(format!("{e}")))?,
        );
        let id: u64 = {
            let mut h = std::collections::hash_map::DefaultHasher::new();
            window.id().hash(&mut h);
            h.finish()
        };
        #[cfg(target_os = "windows")]
        let transparent_surface = if self.transparent {
            Some(create_transparent_surface(window.clone())?)
        } else {
            None
        };
        Ok(TaoWindow {
            inner: window,
            id,
            #[cfg(target_os = "windows")]
            transparent_surface: RefCell::new(transparent_surface),
        })
    }
}

// ── TaoWindow ─────────────────────────────────────────────────────────────

/// A managed window created from :class:`TaoWindowBuilder`.
///
/// .. warning::
///    **Not sendable** to other Python threads.  All window operations
///    must happen on the event loop thread.
#[pyclass(unsendable)]
pub struct TaoWindow {
    inner: Arc<Window>,
    /// Deterministic hash of the tao ``WindowId``.  Matches the
    /// ``window_id`` field on every window event, so the Python
    /// layer can route events to the correct ``Window`` without
    /// any additional mapping tables.
    pub(crate) id: u64,
    /// Tao configures DWM transparency but does not submit an alpha-cleared
    /// client surface. Without this retained surface, Windows keeps the
    /// initial client rectangle as an opaque (usually white) bitmap.
    #[cfg(target_os = "windows")]
    transparent_surface: RefCell<Option<TransparentSurface>>,
}

#[cfg(target_os = "windows")]
type TransparentSurface = softbuffer::Surface<Arc<Window>, Arc<Window>>;

#[cfg(target_os = "windows")]
fn draw_transparent_surface(
    window: &Arc<Window>,
    surface: &mut TransparentSurface,
) -> PyResult<()> {
    let size = window.inner_size();
    let (Some(width), Some(height)) = (
        std::num::NonZeroU32::new(size.width),
        std::num::NonZeroU32::new(size.height),
    ) else {
        return Ok(());
    };

    surface
        .resize(width, height)
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    let mut buffer = surface
        .buffer_mut()
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    buffer.fill(0);
    buffer
        .present()
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))
}

#[cfg(target_os = "windows")]
fn create_transparent_surface(window: Arc<Window>) -> PyResult<TransparentSurface> {
    let context = softbuffer::Context::new(window.clone())
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    let mut surface = softbuffer::Surface::new(&context, window.clone())
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    draw_transparent_surface(&window, &mut surface)?;
    Ok(surface)
}

impl TaoWindow {
    fn refresh_transparent_surface(&self) -> PyResult<()> {
        #[cfg(target_os = "windows")]
        if let Some(surface) = self.transparent_surface.borrow_mut().as_mut() {
            draw_transparent_surface(&self.inner, surface)?;
        }
        Ok(())
    }
}

#[pymethods]
impl TaoWindow {
    /// Returns the unique identifier for this window.
    ///
    /// Use this to match events to windows in multi-window applications:
    ///
    ///     win1_id = win1.id()
    ///     def on_event(event):
    ///         if event.window_id == win1_id:
    ///             ...
    fn id(&self) -> u64 {
        self.id
    }

    // ── Native handle ────────────────────────────────────────────────────

    /// Returns the native window/area handle as an integer:
    ///
    /// ============= ===========================
    /// Platform      Handle
    /// ============= ===========================
    /// Windows       HWND
    /// macOS         NSView pointer
    /// Linux X11     XID (``Window``)
    /// Linux Wayland ``wl_surface`` pointer
    /// ============= ===========================
    fn native_handle(&self) -> PyResult<isize> {
        use raw_window_handle::HasWindowHandle;
        let wh = self
            .inner
            .window_handle()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
        match wh.as_raw() {
            #[cfg(target_os = "windows")]
            raw_window_handle::RawWindowHandle::Win32(h) => Ok(h.hwnd.get()),
            #[cfg(target_os = "macos")]
            raw_window_handle::RawWindowHandle::AppKit(h) => Ok(h.ns_view.as_ptr() as isize),
            #[cfg(all(unix, not(target_os = "macos")))]
            raw_window_handle::RawWindowHandle::Xlib(h) => Ok(h.window as isize),
            #[cfg(all(unix, not(target_os = "macos")))]
            raw_window_handle::RawWindowHandle::Wayland(h) => Ok(h.surface.as_ptr() as isize),
            _ => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "unsupported platform",
            )),
        }
    }

    /// Returns the platform-specific handle kind.
    fn native_handle_kind(&self) -> PyResult<WindowHandleKind> {
        use raw_window_handle::HasWindowHandle;
        let wh = self
            .inner
            .window_handle()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{e}")))?;
        match wh.as_raw() {
            #[cfg(target_os = "windows")]
            raw_window_handle::RawWindowHandle::Win32(_) => Ok(WindowHandleKind::Win32),
            #[cfg(target_os = "macos")]
            raw_window_handle::RawWindowHandle::AppKit(_) => Ok(WindowHandleKind::AppKit),
            #[cfg(all(unix, not(target_os = "macos")))]
            raw_window_handle::RawWindowHandle::Xlib(_) => Ok(WindowHandleKind::X11),
            #[cfg(all(unix, not(target_os = "macos")))]
            raw_window_handle::RawWindowHandle::Wayland(_) => Ok(WindowHandleKind::Wayland),
            _ => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "unsupported platform",
            )),
        }
    }

    // ── Geometry ─────────────────────────────────────────────────────────

    fn set_inner_size(&self, width: f64, height: f64) -> PyResult<()> {
        self.inner.set_inner_size(LogicalSize::new(width, height));
        self.refresh_transparent_surface()?;
        self.inner.request_redraw();
        Ok(())
    }

    /// Logical inner size (DPI-aware). Same unit as ``ResizedEvent``.
    fn inner_size(&self) -> (f64, f64) {
        let size = self.inner.inner_size();
        let sf = self.inner.scale_factor();
        (size.width as f64 / sf, size.height as f64 / sf)
    }

    /// Physical outer size (raw pixels).
    fn outer_size(&self) -> (u32, u32) {
        let size = self.inner.outer_size();
        (size.width, size.height)
    }

    fn set_outer_position(&self, x: f64, y: f64) {
        self.inner.set_outer_position(LogicalPosition::new(x, y));
    }

    fn set_min_inner_size(&self, width: f64, height: f64) {
        self.inner
            .set_min_inner_size(Some(LogicalSize::new(width, height)));
    }

    fn set_max_inner_size(&self, width: f64, height: f64) {
        self.inner
            .set_max_inner_size(Some(LogicalSize::new(width, height)));
    }

    // ── Appearance ───────────────────────────────────────────────────────

    fn set_title(&self, title: &str) {
        self.inner.set_title(title);
    }

    fn set_visible(&self, visible: bool) {
        self.inner.set_visible(visible);
    }

    fn set_resizable(&self, resizable: bool) {
        self.inner.set_resizable(resizable);
    }

    fn set_minimizable(&self, minimizable: bool) {
        self.inner.set_minimizable(minimizable);
    }

    fn set_maximizable(&self, maximizable: bool) {
        self.inner.set_maximizable(maximizable);
    }

    fn set_closable(&self, closable: bool) {
        self.inner.set_closable(closable);
    }

    fn set_always_on_top(&self, always: bool) {
        self.inner.set_always_on_top(always);
    }

    fn set_cursor_visible(&self, visible: bool) {
        self.inner.set_cursor_visible(visible);
    }

    fn set_decorations(&self, decorations: bool) {
        self.inner.set_decorations(decorations);
    }

    fn apply_effect(&self, effect: WindowEffect, color: Option<(u8, u8, u8, u8)>) -> PyResult<()> {
        let result = match effect {
            WindowEffect::Blur => window_vibrancy::apply_blur(&self.inner, color),
            WindowEffect::Acrylic => window_vibrancy::apply_acrylic(&self.inner, color),
            WindowEffect::Mica => window_vibrancy::apply_mica(&self.inner, None),
            WindowEffect::Vibrancy => window_vibrancy::apply_vibrancy(
                &self.inner,
                NSVisualEffectMaterial::Sidebar,
                Some(NSVisualEffectState::FollowsWindowActiveState),
                None,
            ),
        };
        result.map_err(effect_error)?;
        self.refresh_transparent_surface()
    }

    fn clear_effect(&self, effect: WindowEffect) -> PyResult<()> {
        let result = match effect {
            WindowEffect::Blur => window_vibrancy::clear_blur(&self.inner),
            WindowEffect::Acrylic => window_vibrancy::clear_acrylic(&self.inner),
            WindowEffect::Mica => window_vibrancy::clear_mica(&self.inner),
            WindowEffect::Vibrancy => window_vibrancy::clear_vibrancy(&self.inner).map(|_| ()),
        };
        result.map_err(effect_error)
    }

    // ── State ────────────────────────────────────────────────────────────

    fn is_minimized(&self) -> bool {
        self.inner.is_minimized()
    }

    fn is_maximized(&self) -> bool {
        self.inner.is_maximized()
    }

    fn is_visible(&self) -> bool {
        self.inner.is_visible()
    }

    fn set_minimized(&self, minimized: bool) {
        self.inner.set_minimized(minimized);
    }

    fn set_maximized(&self, maximized: bool) {
        self.inner.set_maximized(maximized);
    }

    fn set_fullscreen(&self, fullscreen: bool) {
        use tao::window::Fullscreen;
        if fullscreen {
            self.inner
                .set_fullscreen(Some(Fullscreen::Borderless(None)));
        } else {
            self.inner.set_fullscreen(None);
        }
    }

    // ── Icon ─────────────────────────────────────────────────────────────

    /// Set the window icon from raw RGBA pixel data.
    fn set_window_icon(&self, width: u32, height: u32, rgba: Vec<u8>) -> PyResult<()> {
        let icon = tao::window::Icon::from_rgba(rgba, width, height).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid icon: {e}"))
        })?;
        self.inner.set_window_icon(Some(icon));
        Ok(())
    }

    // ── Focus ────────────────────────────────────────────────────────────

    fn set_focused(&self, focused: bool) {
        if focused {
            self.inner.set_focus();
        }
    }

    // ── Interaction ──────────────────────────────────────────────────────

    fn drag_window(&self) -> PyResult<()> {
        self.inner.drag_window().map_err(interaction_error)
    }

    fn drag_resize_window(&self, direction: ResizeDirection) -> PyResult<()> {
        self.inner
            .drag_resize_window(direction.into())
            .map_err(interaction_error)
    }

    fn scale_factor(&self) -> f64 {
        self.inner.scale_factor()
    }

    fn request_redraw(&self) {
        self.inner.request_redraw();
    }

    /// Refresh the retained transparent client surface after a native redraw.
    ///
    /// Internal lifecycle hook used by the Python event dispatcher.
    fn _redraw_transparent_surface(&self) -> PyResult<()> {
        self.refresh_transparent_surface()
    }

    // ── Linux GTK ────────────────────────────────────────────────────────

    /// Returns the raw pointer to the default ``gtk::Box`` container child
    /// of this window.
    ///
    /// **Linux only.**  Pass this to wryview together with
    /// ``parent_hwnd_kind=WindowHandleKind.Gtk`` to embed a WebView that
    /// works on both X11 and Wayland::
    ///
    ///     if sys.platform == "linux":
    ///         wv = WebView(window.gtk_container(),
    ///                      parent_hwnd_kind=WindowHandleKind.Gtk)
    ///     else:
    ///         wv = WebView(window.native_handle())
    ///
    /// Returns ``0`` if the default box was disabled at window creation
    /// (via ``WindowBuilderExtUnix::with_default_vbox(false)``).
    #[cfg(all(unix, not(target_os = "macos")))]
    fn gtk_container(&self) -> isize {
        use gtk::glib::ObjectType;
        use tao::platform::unix::WindowExtUnix;
        self.inner
            .default_vbox()
            .map(|vbox| vbox.as_ptr() as isize)
            .unwrap_or(0)
    }
}
