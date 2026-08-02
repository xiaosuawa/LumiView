use std::cell::Cell;
use std::ptr::NonNull;

use pyo3::prelude::*;
use tao::event_loop::{
    ControlFlow, EventLoop, EventLoopBuilder, EventLoopProxy, EventLoopWindowTarget,
};
use tao::platform::run_return::EventLoopExtRunReturn;

use crate::events::build_event;
use crate::types::EventLoopControl;

// Thread-local ELWT pointer
//
// DURING run():
//   The callback closure receives `&EventLoopWindowTarget`.
//   We stash a NonNull in RUNNING_PTR before calling into Python,
//   and clear it after. `build()` reads RUNNING_PTR.
//
// This pointer is only accessed from the main (GUI) thread.
// It is cleared between callback invocations.

thread_local! {
    /// Valid only while the event callback is executing.
    /// `TaoWindowBuilder::build()` reads this to obtain the ELWT reference.
    static RUNNING_PTR: Cell<Option<NonNull<EventLoopWindowTarget<String>>>> =
        const { Cell::new(None) };
}

/// Return a reference to the running EventLoopWindowTarget, if available.
///
/// Only valid **during** an event callback — i.e. while ``TaoEventLoop.run()``
/// is executing a callback. Returns ``None`` at all other times.
///
/// # Safety
///
/// The returned reference must NOT outlive the current callback invocation.
/// Callers must use the reference synchronously and not store it.
pub(crate) fn event_loop_target() -> Option<&'static EventLoopWindowTarget<String>> {
    if let Some(ptr) = RUNNING_PTR.with(|c| c.get()) {
        // SAFETY: RUNNING_PTR is set immediately before the Python callback
        // and cleared immediately after. The underlying ELWT lives for the
        // duration of EventLoop::run(), which outlives any single callback.
        Some(unsafe { ptr.as_ref() })
    } else {
        None
    }
}

// SendPtr — private helper for detach()
//
// tao::EventLoop is !Send. pyo3's py.detach() requires the closure to be
// Send so the GIL can be released during the blocking event loop. Without
// releasing the GIL, Python threads (asyncio, worker pool) would deadlock.
//
// SendPtr is a single-purpose, scope-limited wrapper: created immediately
// before detach(), consumed immediately inside the closure. Unlike the old
// SendEventLoop public wrapper type, this is a private implementation detail
// that does not escape this module.
//
// # Safety
//
// The marker is only valid because pyo3's detach() runs the closure on the
// CALLING THREAD — the pointer value never crosses a thread boundary.
// EventLoop::run() also requires the main thread on macOS, providing a
// second layer of protection.

/// Private newtype whose only purpose is satisfying `Send` for pyo3's detach().
struct SendPtr<T>(*mut T);

// SAFETY: SendPtr is created and consumed within the same function scope on
// the same OS thread. It is never actually sent between threads.
unsafe impl<T> Send for SendPtr<T> {}

impl<T> Drop for SendPtr<T> {
    fn drop(&mut self) {
        // SAFETY: If SendPtr is dropped without being unpacked, the Box'd
        // value would leak. This only happens on panic during detach() —
        // pyo3 aborts the process in that case.
        if !self.0.is_null() {
            let _ = unsafe { Box::from_raw(self.0) };
        }
    }
}

// run_event_loop_detached

/// Run the event loop with the GIL released.
///
/// We box the EventLoop, convert the Box to a raw pointer, and wrap it in
/// ``SendPtr`` so the closure satisfies pyo3's ``Send`` bound. The Box is
/// reconstructed on the other side of ``detach()`` — still on the same thread.
///
/// # Safety
///
/// Caller must ensure this runs on the main thread.
unsafe fn run_event_loop_detached(
    py: Python<'_>,
    event_loop: EventLoop<String>,
    callback: Py<PyAny>,
) {
    let el_ptr: *mut EventLoop<String> = Box::into_raw(Box::new(event_loop));
    let send_ptr = SendPtr(el_ptr);

    py.detach(move || {
        // SAFETY: detach() runs on the calling thread. We are on the
        // main thread, same address space — reconstructing the Box is safe.
        let mut el: Box<EventLoop<String>> = unsafe { Box::from_raw(send_ptr.0) };
        // Prevent SendPtr's Drop from double-freeing.
        std::mem::forget(send_ptr);

        // run_return (vs run) exits when ControlFlow::Exit is set, but
        // during OS modal loops (e.g. window resize on Windows/macOS)
        // tao defers returning until the gesture ends — events keep
        // flowing, only the return is delayed. Known limitation.
        el.run_return(move |event, elwt, control_flow| {
            *control_flow = ControlFlow::Wait;

            // Stash ELWT pointer for build() during this callback.
            RUNNING_PTR.with(|c| c.set(Some(NonNull::from(elwt))));

            // Re-acquire the GIL to create Python event objects.
            Python::attach(|py| {
                let evt = match build_event(py, &event) {
                    Some(e) => e,
                    None => {
                        RUNNING_PTR.with(|c| c.set(None));
                        return;
                    }
                };

                let cf: Cell<ControlFlow> = Cell::new(*control_flow);
                match callback.call1(py, (evt,)) {
                    Ok(val) => {
                        if let Ok(ctrl) = val.extract::<EventLoopControl>(py) {
                            if ctrl == EventLoopControl::Exit {
                                cf.set(ControlFlow::Exit);
                            }
                        }
                    }
                    Err(e) => {
                        e.write_unraisable(py, Some(callback.bind(py)));
                    }
                }
                *control_flow = cf.get();
            });

            // Clear the pointer — no longer valid after callback returns.
            RUNNING_PTR.with(|c| c.set(None));
        });

        // Box<EventLoop> is dropped here after run_return() returns.
    });

    // Paranoia: clear the pointer after run() returns.
    RUNNING_PTR.with(|c| c.set(None));
}

// TaoEventLoop

/// Cross-platform event loop. Create exactly one per application.
///
/// .. warning::
///    **Not sendable** to other Python threads. Always create and run
///    the event loop on the main thread, especially on macOS where AppKit
///    requires it.
#[pyclass(unsendable)]
pub struct TaoEventLoop {
    pub inner: Option<EventLoop<String>>,
}

#[pymethods]
impl TaoEventLoop {
    #[new]
    fn new() -> Self {
        let el = EventLoopBuilder::<String>::with_user_event().build();
        TaoEventLoop { inner: Some(el) }
    }

    /// Run the event loop. Calls ``callback(event)`` for each interesting event.
    ///
    /// The callback receives a subclass of :class:`TaoEvent` — use
    /// ``isinstance()`` to dispatch.
    ///
    /// Return ``EventLoopControl.Exit`` to stop the loop,
    /// or ``EventLoopControl.Continue`` (or ``None``) to keep running.
    ///
    /// .. warning::
    ///    ``TaoWindowBuilder.build()`` **only** works during event callbacks
    ///    (i.e. while ``run()`` is active). Call it from within your event
    ///    handler or a ``call_on_main`` dispatch.
    fn run(&mut self, py: Python<'_>, callback: Py<PyAny>) {
        let event_loop = self.inner.take().expect("EventLoop already consumed");

        // SAFETY: We are on the main thread (enforced by pyo3's unsendable
        // guard on TaoEventLoop). The EventLoop is converted to a raw pointer
        // and reconstructed inside the detach closure on the same thread.
        unsafe {
            run_event_loop_detached(py, event_loop, callback);
        }
    }

    /// Create a thread-safe proxy for sending events from other threads.
    fn create_proxy(&self) -> PyResult<TaoEventLoopProxy> {
        let inner = self.inner.as_ref().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("EventLoop already consumed")
        })?;
        Ok(TaoEventLoopProxy {
            proxy: inner.create_proxy(),
        })
    }
}

// TaoEventLoopProxy

/// Thread-safe handle for sending user events into the event loop.
///
/// Create via ``el.create_proxy()`` **before** calling ``el.run()``.
/// Can be passed to ``threading.Thread`` targets safely.
///
/// Each call to :meth:`send_event` results in a :class:`UserEvent` in the
/// main event loop.
#[pyclass]
pub struct TaoEventLoopProxy {
    proxy: EventLoopProxy<String>,
}

#[pymethods]
impl TaoEventLoopProxy {
    /// Send a data string into the event loop from any thread.
    ///
    /// The event loop will dispatch a :class:`UserEvent` with the
    /// :attr:`~UserEvent.data` field set to this string.
    ///
    /// Raises ``RuntimeError`` if the event loop has been closed.
    fn send_event(&self, data: String) -> PyResult<()> {
        self.proxy
            .send_event(data)
            .map_err(|_| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Event loop closed"))
    }

    fn __repr__(&self) -> String {
        "TaoEventLoopProxy()".into()
    }
}
