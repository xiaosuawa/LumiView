#[cfg(target_os = "windows")]
use std::cell::RefCell;
use std::hash::{Hash, Hasher};
use std::sync::Arc;

use pyo3::exceptions::{PyNotImplementedError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use tao::dpi::{LogicalPosition, LogicalSize};
use tao::window::{Icon, Window, WindowBuilder};
use window_vibrancy::NSVisualEffectState;

use crate::event_loop::TaoEventLoop;
use crate::monitor::{Monitor, VideoMode};
use crate::types::{
    AttentionType, CursorIcon, ProgressState, ResizeDirection, Theme, VibrancyMaterial,
    WindowEffect, WindowHandleKind,
};

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

// TaoWindow

/// A native window.
///
/// Construct directly with ``TaoWindow(event_loop, **options)`` — all
/// options are keyword-only and ``None`` means "leave the platform
/// default". *event_loop* must be the running :class:`TaoEventLoop`.
///
/// .. warning::
///    **Not sendable** to other Python threads — all window operations
///    must happen on the main thread (the event loop thread). The Python
///    layer's ``call_on_main`` bridge dispatches operations there.
#[pyclass(unsendable)]
pub struct TaoWindow {
    inner: Arc<Window>,
    /// Deterministic hash of the tao ``WindowId``. Matches the
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
    /// Create a window. All options are keyword-only; ``None`` means
    /// "leave the platform default".
    #[new]
    // Deliberate consequence of builder deletion: all options are keyword-only.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        event_loop,
        *,
        title = None, width = None, height = None,
        min_size = None, max_size = None, position = None,
        resizable = None, minimizable = None, maximizable = None,
        closable = None, maximized = None, visible = None,
        decorations = None, undecorated_shadow = None,
        always_on_top = None, focused = None, focusable = None,
        content_protection = None, visible_on_all_workspaces = None,
        transparent = None, icon = None,
        always_on_bottom = None, background_color = None,
        titlebar_transparent = None, titlebar_hidden = None,
        title_hidden = None, titlebar_buttons_hidden = None,
        fullsize_content_view = None, traffic_light_inset = None,
        movable_by_background = None,
    ))]
    fn new(
        event_loop: &TaoEventLoop,
        title: Option<String>,
        width: Option<f64>,
        height: Option<f64>,
        min_size: Option<(f64, f64)>,
        max_size: Option<(f64, f64)>,
        position: Option<(f64, f64)>,
        resizable: Option<bool>,
        minimizable: Option<bool>,
        maximizable: Option<bool>,
        closable: Option<bool>,
        maximized: Option<bool>,
        visible: Option<bool>,
        decorations: Option<bool>,
        undecorated_shadow: Option<bool>,
        always_on_top: Option<bool>,
        focused: Option<bool>,
        focusable: Option<bool>,
        content_protection: Option<bool>,
        visible_on_all_workspaces: Option<bool>,
        transparent: Option<bool>,
        icon: Option<(u32, u32, Vec<u8>)>,
        always_on_bottom: Option<bool>,
        background_color: Option<(u8, u8, u8, u8)>,
        // macOS titlebar group (see TitleBarOptions in the Python layer)
        titlebar_transparent: Option<bool>,
        titlebar_hidden: Option<bool>,
        title_hidden: Option<bool>,
        titlebar_buttons_hidden: Option<bool>,
        fullsize_content_view: Option<bool>,
        traffic_light_inset: Option<(f64, f64)>,
        movable_by_background: Option<bool>,
    ) -> PyResult<TaoWindow> {
        let elwt = event_loop.target().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                "EventLoop is not running — create windows while el.run() is active",
            )
        })?;

        // width/height must come in pairs — a lone value would be silently
        // ignored by the builder below (keyword-only API).
        if width.is_some() != height.is_some() {
            return Err(PyValueError::new_err(
                "width and height must be specified together",
            ));
        }

        let mut b = WindowBuilder::new();
        if let Some(title) = title {
            b = b.with_title(title);
        }
        if let (Some(w), Some(h)) = (width, height) {
            b = b.with_inner_size(LogicalSize::new(w, h));
        }
        if let Some((w, h)) = min_size {
            b = b.with_min_inner_size(LogicalSize::new(w, h));
        }
        if let Some((w, h)) = max_size {
            b = b.with_max_inner_size(LogicalSize::new(w, h));
        }
        if let Some((x, y)) = position {
            b = b.with_position(LogicalPosition::new(x, y));
        }
        if let Some(v) = resizable {
            b = b.with_resizable(v);
        }
        if let Some(v) = minimizable {
            b = b.with_minimizable(v);
        }
        if let Some(v) = maximizable {
            b = b.with_maximizable(v);
        }
        if let Some(v) = closable {
            b = b.with_closable(v);
        }
        if let Some(v) = maximized {
            b = b.with_maximized(v);
        }
        if let Some(v) = visible {
            b = b.with_visible(v);
        }
        if let Some(v) = decorations {
            b = b.with_decorations(v);
        }
        if let Some(v) = transparent {
            b = b.with_transparent(v);
        }
        // Windows only: DWM's hidden non-client border can leave a stale
        // edge while resizing transparent custom-chrome windows.
        #[cfg(target_os = "windows")]
        if let Some(shadow) = undecorated_shadow {
            use tao::platform::windows::WindowBuilderExtWindows;
            b = b.with_undecorated_shadow(shadow);
        }
        #[cfg(not(target_os = "windows"))]
        let _ = undecorated_shadow;
        if let Some(v) = always_on_top {
            b = b.with_always_on_top(v);
        }
        // tao treats always-on-top/bottom as mutually exclusive — the
        // later call wins.
        if let Some(v) = always_on_bottom {
            b = b.with_always_on_bottom(v);
        }
        if let Some(color) = background_color {
            // Windows ignores the alpha channel (tao behavior).
            b = b.with_background_color(color);
        }
        // macOS titlebar group — mirrors TitleBarOptions in the Python
        // layer; silently ignored on other platforms.
        #[cfg(target_os = "macos")]
        {
            use tao::platform::macos::WindowBuilderExtMacOS;
            if let Some(v) = titlebar_transparent {
                b = b.with_titlebar_transparent(v);
            }
            if let Some(v) = titlebar_hidden {
                b = b.with_titlebar_hidden(v);
            }
            if let Some(v) = title_hidden {
                b = b.with_title_hidden(v);
            }
            if let Some(v) = titlebar_buttons_hidden {
                b = b.with_titlebar_buttons_hidden(v);
            }
            if let Some(v) = fullsize_content_view {
                b = b.with_fullsize_content_view(v);
            }
            if let Some((x, y)) = traffic_light_inset {
                b = b.with_traffic_light_inset(LogicalPosition::new(x, y));
            }
            if let Some(v) = movable_by_background {
                b = b.with_movable_by_window_background(v);
            }
        }
        #[cfg(not(target_os = "macos"))]
        let _ = (
            titlebar_transparent,
            titlebar_hidden,
            title_hidden,
            titlebar_buttons_hidden,
            fullsize_content_view,
            traffic_light_inset,
            movable_by_background,
        );
        if let Some(v) = focused {
            b = b.with_focused(v);
        }
        if let Some(v) = focusable {
            b = b.with_focusable(v);
        }
        if let Some(v) = content_protection {
            b = b.with_content_protection(v);
        }
        if let Some(v) = visible_on_all_workspaces {
            b = b.with_visible_on_all_workspaces(v);
        }
        if let Some((iw, ih, rgba)) = icon {
            let ic = Icon::from_rgba(rgba, iw, ih).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid icon: {e}"))
            })?;
            b = b.with_window_icon(Some(ic));
        }

        let window = Arc::new(
            b.build(elwt)
                .map_err(|e| PyRuntimeError::new_err(format!("{e}")))?,
        );
        let id: u64 = {
            let mut h = std::collections::hash_map::DefaultHasher::new();
            window.id().hash(&mut h);
            h.finish()
        };
        #[cfg(target_os = "windows")]
        let transparent_surface = if transparent.unwrap_or(false) {
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

    // Native handle

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

    // Geometry

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

    /// Logical inner position of the window's client area, relative to
    /// the top-left of the screen. Raises ``NotImplementedError`` on
    /// platforms that cannot report it (Wayland).
    fn inner_position(&self) -> PyResult<(f64, f64)> {
        let pos = self.inner.inner_position().map_err(|_| {
            PyNotImplementedError::new_err("inner position is not supported on this platform")
        })?;
        let sf = self.inner.scale_factor();
        Ok((pos.x as f64 / sf, pos.y as f64 / sf))
    }

    /// Logical outer position of the window, relative to the top-left
    /// of the screen.
    fn outer_position(&self) -> PyResult<(f64, f64)> {
        let pos = self.inner.outer_position().map_err(|_| {
            PyNotImplementedError::new_err("outer position is not supported on this platform")
        })?;
        let sf = self.inner.scale_factor();
        Ok((pos.x as f64 / sf, pos.y as f64 / sf))
    }

    /// Logical cursor position inside the window client area.
    fn cursor_position(&self) -> PyResult<(f64, f64)> {
        let pos = self
            .inner
            .cursor_position()
            .map_err(interaction_error)?;
        let sf = self.inner.scale_factor();
        Ok((pos.x as f64 / sf, pos.y as f64 / sf))
    }

    // Appearance

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

    #[pyo3(signature = (effect, color = None, material = None))]
    fn apply_effect(
        &self,
        effect: WindowEffect,
        color: Option<(u8, u8, u8, u8)>,
        material: Option<VibrancyMaterial>,
    ) -> PyResult<()> {
        // *material* only applies to Vibrancy — ignore it for the
        // Windows effects, matching the platform's one-parameter APIs.
        let result = match effect {
            WindowEffect::Blur => window_vibrancy::apply_blur(&self.inner, color),
            WindowEffect::Acrylic => window_vibrancy::apply_acrylic(&self.inner, color),
            WindowEffect::Mica => window_vibrancy::apply_mica(&self.inner, None),
            WindowEffect::Vibrancy => window_vibrancy::apply_vibrancy(
                &self.inner,
                material
                    .unwrap_or(VibrancyMaterial::Sidebar)
                    .into(),
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

    /// Set the window background color (``None`` restores the platform
    /// default). On Windows the alpha channel is ignored.
    fn set_background_color(&self, color: Option<(u8, u8, u8, u8)>) {
        self.inner.set_background_color(color);
    }

    // State

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

    /// Enter borderless fullscreen on *monitor* (``None`` = the
    /// current monitor).
    fn set_borderless_fullscreen(&self, monitor: Option<&Monitor>) {
        use tao::window::Fullscreen;
        let m = monitor.map(|m| m.inner.clone());
        self.inner.set_fullscreen(Some(Fullscreen::Borderless(m)));
    }

    /// Enter exclusive fullscreen on the monitor of *mode* at the
    /// mode's resolution and refresh rate.
    fn set_exclusive_fullscreen(&self, mode: &VideoMode) {
        use tao::window::Fullscreen;
        self.inner
            .set_fullscreen(Some(Fullscreen::Exclusive(mode.inner.clone())));
    }

    /// Current fullscreen state.
    fn is_fullscreen(&self) -> bool {
        self.inner.fullscreen().is_some()
    }

    fn is_focused(&self) -> bool {
        self.inner.is_focused()
    }

    fn is_resizable(&self) -> bool {
        self.inner.is_resizable()
    }

    fn is_decorated(&self) -> bool {
        self.inner.is_decorated()
    }

    fn is_closable(&self) -> bool {
        self.inner.is_closable()
    }

    fn is_minimizable(&self) -> bool {
        self.inner.is_minimizable()
    }

    fn is_maximizable(&self) -> bool {
        self.inner.is_maximizable()
    }

    fn is_always_on_top(&self) -> bool {
        self.inner.is_always_on_top()
    }

    /// The current window title.
    fn title(&self) -> String {
        self.inner.title()
    }

    /// The window's effective color theme.
    fn theme(&self) -> Theme {
        Theme::from(self.inner.theme())
    }

    /// Force the window theme (``None`` restores the system default).
    fn set_theme(&self, theme: Option<Theme>) {
        let t = theme.map(|t| match t {
            Theme::Light => tao::window::Theme::Light,
            Theme::Dark => tao::window::Theme::Dark,
        });
        self.inner.set_theme(t);
    }

    fn set_focusable(&self, focusable: bool) {
        self.inner.set_focusable(focusable);
    }

    fn set_content_protection(&self, enabled: bool) {
        self.inner.set_content_protection(enabled);
    }

    fn set_visible_on_all_workspaces(&self, visible: bool) {
        self.inner.set_visible_on_all_workspaces(visible);
    }

    fn set_always_on_bottom(&self, always: bool) {
        self.inner.set_always_on_bottom(always);
    }

    // Cursor

    /// Set the cursor shape shown while hovering the window.
    fn set_cursor_icon(&self, cursor: CursorIcon) {
        self.inner.set_cursor_icon(cursor.into());
    }

    /// Lock (``True``) or release (``False``) the cursor to the window.
    /// Useful for games or drawing apps.
    fn set_cursor_grab(&self, grab: bool) -> PyResult<()> {
        self.inner.set_cursor_grab(grab).map_err(interaction_error)
    }

    /// Make the window transparent to mouse events (``True`` = clicks
    /// pass through).
    fn set_ignore_cursor_events(&self, ignore: bool) -> PyResult<()> {
        self.inner
            .set_ignore_cursor_events(ignore)
            .map_err(interaction_error)
    }

    /// Move the cursor to a logical position inside the window.
    fn set_cursor_position(&self, x: f64, y: f64) -> PyResult<()> {
        self.inner
            .set_cursor_position(LogicalPosition::new(x, y))
            .map_err(interaction_error)
    }

    // Attention

    /// Ask the OS to draw the user's attention to this window
    /// (taskbar flash / Dock bounce). ``None`` clears the request.
    fn request_user_attention(&self, request_type: Option<AttentionType>) {
        self.inner
            .request_user_attention(request_type.map(Into::into));
    }

    // IME

    /// Place the input method editor (candidate window) at a logical
    /// position inside the window.
    fn set_ime_position(&self, x: f64, y: f64) {
        self.inner.set_ime_position(LogicalPosition::new(x, y));
    }

    // Progress bar (Windows taskbar)

    /// Set the Windows taskbar progress bar. ``state=None`` removes it;
    /// *progress* is 0.0–100.0 (ignored for ``Indeterminate``).
    fn set_progress_bar(&self, state: Option<ProgressState>, progress: Option<f64>) {
        use tao::window::ProgressBarState;
        let progress = progress.map(|p| p.clamp(0.0, 100.0) as u64);
        self.inner.set_progress_bar(ProgressBarState {
            state: state.map(Into::into),
            progress,
            desktop_filename: None,
        });
    }

    // Monitors

    /// The monitor the window is currently on, if any.
    fn current_monitor(&self) -> Option<Monitor> {
        self.inner.current_monitor().map(|m| Monitor { inner: m })
    }

    /// All monitors currently connected.
    fn available_monitors(&self) -> Vec<Monitor> {
        self.inner
            .available_monitors()
            .map(|m| Monitor { inner: m })
            .collect()
    }

    /// The primary monitor, if any.
    fn primary_monitor(&self) -> Option<Monitor> {
        self.inner.primary_monitor().map(|m| Monitor { inner: m })
    }

    /// The monitor that contains the given physical screen point.
    fn monitor_from_point(&self, x: f64, y: f64) -> Option<Monitor> {
        self.inner
            .monitor_from_point(x, y)
            .map(|m| Monitor { inner: m })
    }

    // Icon

    /// Set the window icon from raw RGBA pixel data.
    fn set_window_icon(&self, width: u32, height: u32, rgba: Vec<u8>) -> PyResult<()> {
        let icon = Icon::from_rgba(rgba, width, height).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("invalid icon: {e}"))
        })?;
        self.inner.set_window_icon(Some(icon));
        Ok(())
    }

    // Focus

    fn set_focused(&self, focused: bool) {
        if focused {
            self.inner.set_focus();
        }
    }

    // Interaction

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

    // Linux GTK

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
    /// Returns ``0`` if no default box is present.
    #[cfg(all(unix, not(target_os = "macos")))]
    fn gtk_container(&self) -> isize {
        use gtk::glib::ObjectType;
        use tao::platform::unix::WindowExtUnix;
        self.inner
            .default_vbox()
            .map(|vbox| vbox.as_ptr() as isize)
            .unwrap_or(0)
    }

    // ── Platform extensions ────────────────────────────────────────────
    // Each group exists only on its platform (like ``gtk_container``):
    // calling it elsewhere raises AttributeError.

    // Windows

    /// Hide (``True``) or show (``False``) the window in the taskbar.
    /// **Windows only.**
    #[cfg(target_os = "windows")]
    fn set_skip_taskbar(&self, skip: bool) -> PyResult<()> {
        use tao::platform::windows::WindowExtWindows;
        self.inner.set_skip_taskbar(skip).map_err(interaction_error)
    }

    /// Replace the taskbar icon (``None`` restores the window icon).
    /// **Windows only.**
    #[cfg(target_os = "windows")]
    fn set_taskbar_icon(&self, icon: Option<(u32, u32, Vec<u8>)>) -> PyResult<()> {
        use tao::platform::windows::WindowExtWindows;
        let icon = match icon {
            Some((w, h, rgba)) => Some(Icon::from_rgba(rgba, w, h).map_err(|e| {
                PyErr::new::<PyValueError, _>(format!("invalid icon: {e}"))
            })?),
            None => None,
        };
        self.inner.set_taskbar_icon(icon);
        Ok(())
    }

    /// Set an overlay badge on the taskbar icon (``None`` removes it).
    /// **Windows only.**
    #[cfg(target_os = "windows")]
    fn set_overlay_icon(&self, icon: Option<(u32, u32, Vec<u8>)>) -> PyResult<()> {
        use tao::platform::windows::WindowExtWindows;
        let icon = match icon {
            Some((w, h, rgba)) => Some(Icon::from_rgba(rgba, w, h).map_err(|e| {
                PyErr::new::<PyValueError, _>(format!("invalid icon: {e}"))
            })?),
            None => None,
        };
        self.inner.set_overlay_icon(icon.as_ref());
        Ok(())
    }

    /// Enable (``True``) or disable (``False``) the window (disabled
    /// windows ignore mouse input). **Windows only.**
    #[cfg(target_os = "windows")]
    fn set_enable(&self, enabled: bool) {
        use tao::platform::windows::WindowExtWindows;
        self.inner.set_enable(enabled);
    }

    /// Right-to-left layout for the window. **Windows only.**
    #[cfg(target_os = "windows")]
    fn set_rtl(&self, rtl: bool) {
        use tao::platform::windows::WindowExtWindows;
        self.inner.set_rtl(rtl);
    }

    /// Reset the OS dead-key state (e.g. after AltGr combos). **Windows only.**
    #[cfg(target_os = "windows")]
    fn reset_dead_keys(&self) {
        use tao::platform::windows::WindowExtWindows;
        self.inner.reset_dead_keys();
    }

    /// Toggle the shadow of an undecorated window at runtime.
    /// **Windows only.**
    #[cfg(target_os = "windows")]
    fn set_undecorated_shadow(&self, shadow: bool) {
        use tao::platform::windows::WindowExtWindows;
        self.inner.set_undecorated_shadow(shadow);
    }

    /// Whether the undecorated window shadow is currently enabled.
    /// **Windows only.**
    #[cfg(target_os = "windows")]
    fn has_undecorated_shadow(&self) -> bool {
        use tao::platform::windows::WindowExtWindows;
        self.inner.has_undecorated_shadow()
    }

    // macOS

    /// Set the text shown in the macOS Dock badge (``None`` clears it).
    /// **macOS only.**
    #[cfg(target_os = "macos")]
    fn set_badge_label(&self, label: Option<String>) {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.set_badge_label(label);
    }

    /// Toggle "simple fullscreen" (content covers the whole screen,
    /// including the menu bar). Returns the resulting state.
    /// **macOS only.**
    #[cfg(target_os = "macos")]
    fn set_simple_fullscreen(&self, fullscreen: bool) -> bool {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.set_simple_fullscreen(fullscreen)
    }

    /// Make the native titlebar transparent (custom chrome overlays
    /// the titlebar area). **macOS only.**
    #[cfg(target_os = "macos")]
    fn set_titlebar_transparent(&self, transparent: bool) {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.set_titlebar_transparent(transparent);
    }

    /// Set the traffic-light (window controls) inset in logical points.
    /// **macOS only.**
    #[cfg(target_os = "macos")]
    fn set_traffic_light_inset(&self, x: f64, y: f64) {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.set_traffic_light_inset(LogicalPosition::new(x, y));
    }

    /// Make the window content appear behind the titlebar
    /// (``NSFullSizeContentViewWindowMask``). **macOS only.**
    #[cfg(target_os = "macos")]
    fn set_fullsize_content_view(&self, fullsize: bool) {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.set_fullsize_content_view(fullsize);
    }

    /// Toggle the window shadow. **macOS only.**
    #[cfg(target_os = "macos")]
    fn set_has_shadow(&self, has_shadow: bool) {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.set_has_shadow(has_shadow);
    }

    /// Whether the window currently has a shadow. **macOS only.**
    #[cfg(target_os = "macos")]
    fn has_shadow(&self) -> bool {
        use tao::platform::macos::WindowExtMacOS;
        self.inner.has_shadow()
    }

    // Linux (GTK)

    /// Hide (``True``) or show (``False``) the window in the taskbar.
    /// **Linux only.**
    #[cfg(all(unix, not(target_os = "macos")))]
    fn set_skip_taskbar(&self, skip: bool) -> PyResult<()> {
        use tao::platform::unix::WindowExtUnix;
        self.inner.set_skip_taskbar(skip).map_err(interaction_error)
    }

    /// Set the number shown in the GTK badge (``None`` clears it).
    /// **Linux only.**
    #[cfg(all(unix, not(target_os = "macos")))]
    fn set_badge_count(&self, count: Option<i64>) {
        use tao::platform::unix::WindowExtUnix;
        self.inner.set_badge_count(count, None);
    }
}
