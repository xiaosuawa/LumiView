use pyo3::prelude::*;

// Monitor

/// A display monitor connected to the system.
///
/// Query via :meth:`TaoWindow.available_monitors`,
/// :meth:`TaoWindow.primary_monitor`, :meth:`TaoWindow.current_monitor`
/// or :meth:`TaoWindow.monitor_from_point`. Size and position are in
/// physical pixels; use :meth:`scale_factor` to convert.
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct Monitor {
    pub(crate) inner: tao::monitor::MonitorHandle,
}

#[pymethods]
impl Monitor {
    /// Human-readable monitor name (e.g. ``"DELL U2720Q"``), if known.
    fn name(&self) -> Option<String> {
        self.inner.name()
    }

    /// Physical size of the monitor in pixels.
    fn size(&self) -> (u32, u32) {
        let size = self.inner.size();
        (size.width, size.height)
    }

    /// Physical position of the monitor's top-left corner.
    fn position(&self) -> (i32, i32) {
        let pos = self.inner.position();
        (pos.x, pos.y)
    }

    /// DPI scale factor of this monitor.
    fn scale_factor(&self) -> f64 {
        self.inner.scale_factor()
    }

    /// All display modes supported by this monitor, best first.
    fn video_modes(&self) -> Vec<VideoMode> {
        self.inner.video_modes().map(|m| VideoMode { inner: m }).collect()
    }
}

// VideoMode

/// A display mode (resolution + refresh rate + color depth) of a monitor.
///
/// Obtained from :meth:`Monitor.video_modes` — pass one to
/// :meth:`TaoWindow.set_exclusive_fullscreen`.
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct VideoMode {
    pub(crate) inner: tao::monitor::VideoMode,
}

#[pymethods]
impl VideoMode {
    /// Resolution of this mode in physical pixels.
    fn size(&self) -> (u32, u32) {
        let size = self.inner.size();
        (size.width, size.height)
    }

    /// Color depth in bits per pixel.
    fn bit_depth(&self) -> u16 {
        self.inner.bit_depth()
    }

    /// Refresh rate in Hertz.
    fn refresh_rate(&self) -> u16 {
        self.inner.refresh_rate()
    }

    /// The monitor this mode belongs to.
    fn monitor(&self) -> Monitor {
        Monitor {
            inner: self.inner.monitor(),
        }
    }
}
