use std::cell::{Cell, RefCell};
use std::ptr::NonNull;

use pyo3::prelude::*;
use tao::event_loop::{
    ControlFlow, EventLoop, EventLoopBuilder, EventLoopProxy, EventLoopWindowTarget,
};
use tao::platform::run_return::EventLoopExtRunReturn;

use crate::events::build_event;
use crate::types::EventLoopControl;

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

// TargetGuard — RAII cleanup for TaoEventLoop::target
//
// run() stores a pointer to the Box'd EventLoop's inline
// EventLoopWindowTarget. The Box is freed when the detach closure ends —
// normally when run_return returns, or during unwind if the closure panics.
// Clearing the Cell must happen in both cases: a panic that crosses the
// pyo3 boundary surfaces as a catchable PanicException, and a later
// TaoWindow(event_loop, ...) call would dereference freed memory if the
// pointer survived.

/// Clears ``TaoEventLoop::target`` on drop — normal return and panic
/// unwinds alike.
struct TargetGuard<'a>(&'a Cell<Option<NonNull<EventLoopWindowTarget<String>>>>);

impl Drop for TargetGuard<'_> {
    fn drop(&mut self) {
        self.0.set(None);
    }
}

// run_event_loop_detached

/// Run the event loop with the GIL released.
///
/// The caller boxes the EventLoop first so the `EventLoopWindowTarget`
/// pointer stored in ``TaoEventLoop::target`` points at stable heap memory
/// (the ELWT lives inline inside the platform EventLoop). We take the Box,
/// convert it to a raw pointer, and wrap it in ``SendPtr`` so the closure
/// satisfies pyo3's ``Send`` bound. The Box is reconstructed on the other
/// side of ``detach()`` — still on the same thread — and dropped when
/// ``run_return`` returns, which keeps the heap allocation alive for the
/// entire run.
///
/// # Safety
///
/// Caller must ensure this runs on the main thread.
unsafe fn run_event_loop_detached(
    py: Python<'_>,
    event_loop: Box<EventLoop<String>>,
    callback: Py<PyAny>,
) {
    let el_ptr: *mut EventLoop<String> = Box::into_raw(event_loop);
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
        el.run_return(move |event, _elwt, control_flow| {
            *control_flow = ControlFlow::Wait;

            // Re-acquire the GIL to create Python event objects.
            Python::attach(|py| {
                let evt = match build_event(py, &event) {
                    Some(e) => e,
                    None => {
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
        });

        // Box<EventLoop> is dropped here after run_return() returns.
    });
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
    /// RefCell so ``run(&self)`` can consume the EventLoop without holding
    /// a mutable pyclass borrow: the detach closure re-enters Python while
    /// the loop runs (e.g. ``TaoWindow(event_loop, ...)`` from an event
    /// callback), and pyo3 rejects that under an outstanding ``&mut self``.
    inner: RefCell<Option<EventLoop<String>>>,
    /// The `EventLoopWindowTarget` pointer: set when `run()` starts,
    /// cleared when it returns. `run()` boxes the EventLoop first, so the
    /// pointer points at the Box's heap allocation — the Box stays alive
    /// inside the detach closure for the whole run_return, keeping the
    /// heap address stable. Accessed only from the main thread
    /// (TaoEventLoop is unsendable).
    target: Cell<Option<NonNull<EventLoopWindowTarget<String>>>>,
}

#[pymethods]
impl TaoEventLoop {
    #[new]
    fn new() -> Self {
        let el = EventLoopBuilder::<String>::with_user_event().build();
        TaoEventLoop {
            inner: RefCell::new(Some(el)),
            target: Cell::new(None),
        }
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
    ///    ``TaoWindow(event_loop, ...)`` **only** works while ``run()`` is
    ///    active (the ``EventLoopWindowTarget`` pointer is valid only for
    ///    its duration). Call it from within your event handler or a
    ///    ``call_on_main`` dispatch.
    fn run(&self, py: Python<'_>, callback: Py<PyAny>) {
        // Box the EventLoop FIRST, then take the ELWT pointer from the box.
        // The `EventLoopWindowTarget` lives inline inside the platform
        // EventLoop (e.g. `window_target: RootELW<T>` on Windows), so a
        // pointer taken from `self.inner` would dangle as soon as `take()`
        // moves the EventLoop out of the slot. Boxing puts the EventLoop
        // at a stable heap address for the whole run; moving the Box itself
        // does not move the heap allocation.
        let event_loop = self.inner.borrow_mut().take().expect("EventLoop already consumed");
        let boxed = Box::new(event_loop);
        // `EventLoop` derefs to `EventLoopWindowTarget` (tao's API for
        // obtaining the target reference); the annotation coerces through
        // `Deref`.
        let target: &EventLoopWindowTarget<String> = &boxed;
        self.target.set(Some(NonNull::from(target)));
        // RAII: clears the Cell on drop — normal return AND panic unwinds
        // (the Box is freed during unwind, so the pointer must not survive
        // into a catchable PanicException).
        let _guard = TargetGuard(&self.target);

        // SAFETY: We are on the main thread (enforced by pyo3's unsendable
        // guard on TaoEventLoop). The Box is converted to a raw pointer
        // and reconstructed inside the detach closure on the same thread.
        unsafe {
            run_event_loop_detached(py, boxed, callback);
        }

        // _guard drops here — after the detach closure has freed the Box.
    }

    /// Create a thread-safe proxy for sending events from other threads.
    fn create_proxy(&self) -> PyResult<TaoEventLoopProxy> {
        let guard = self.inner.borrow();
        let inner = guard.as_ref().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("EventLoop already consumed")
        })?;
        Ok(TaoEventLoopProxy {
            proxy: inner.create_proxy(),
        })
    }
}

impl TaoEventLoop {
    /// The current `EventLoopWindowTarget` (valid while `run()` is active).
    pub(crate) fn target(&self) -> Option<&'static EventLoopWindowTarget<String>> {
        if let Some(ptr) = self.target.get() {
            // SAFETY: The pointer refers to the Box's heap allocation
            // (moving the Box does not change the heap address). The
            // allocation stays alive in the detach closure for the whole
            // run_return, so the pointer is valid while the closure lives.
            // TargetGuard clears the Cell on drop — on normal return
            // (after the Box is freed) and on panic unwinds (the Box is
            // freed during unwind) — so a dangling pointer can never be
            // read. TaoEventLoop is unsendable, so the pointer is only
            // accessed on the main thread.
            Some(unsafe { ptr.as_ref() })
        } else {
            None
        }
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
