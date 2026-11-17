from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import queue
import signal
import sys
import threading
import time
import uuid
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from typing import Any, Callable, TypeVar, ParamSpec, TYPE_CHECKING

from lumiview._core import (
    ActivationPolicy,
    DeviceAddedEvent,
    DeviceButtonEvent,
    DeviceKeyEvent,
    DeviceMouseMotionEvent,
    DeviceMouseWheelEvent,
    DeviceMotionEvent,
    DeviceTextEvent,
    DeviceRemovedEvent,
    EventLoopControl,
    LoopDestroyedEvent,
    Monitor,
    OpenedEvent,
    ReopenEvent,
    TaoEvent,
    TaoEventLoop,
    TaoEventLoopProxy,
    TrayIconClickEvent,
    TrayIconDoubleClickEvent,
    TrayIconEnterEvent,
    TrayIconLeaveEvent,
    TrayIconMoveEvent,
    UserEvent,
    init_menu_events,
    init_tray_events,
    set_loop_running,
)

from lumiview.events import AppBaseEvent, AppEvent
from lumiview.task import Task, run_async
from lumiview._utils import (
    Subscription,
    _dispatch_event,
    fmt_ms,
    main_thread,
    wait_for_event,
)

P = ParamSpec("P")
T = TypeVar("T")
_E = TypeVar("_E", bound=AppBaseEvent)

_Handler = Callable[..., Any]
_HandlerEntry = tuple[_Handler, Callable[[Any], bool] | None]
_Command = tuple[str, Callable, tuple, dict[str, Any]]

_log = logging.getLogger("lumiview.app")

# The close phase is unbounded; only this post-decision teardown is.
_TEARDOWN_TIMEOUT = 15.0

if TYPE_CHECKING:
    from lumiview import Window


class AppState(Enum):
    """Lifecycle phase of an :class:`App` (monotonic).

    ``RUNNING`` keeps every native resource alive; ``STOPPED`` (the native loop
    returned) is where main-thread work and new tasks start failing. A pending exit
    is not a phase — see :class:`AppEvent.CloseRequestedEvent`.
    """

    CREATED = auto()  # Configured; run() not called yet
    RUNNING = auto()  # Native loop + asyncio thread running
    STOPPED = auto()  # Native loop returned; run() is finishing teardown


class App:
    """Desktop application.

    Create one instance, configure it, then call :meth:`run` (main thread, blocking).
    Cleanup hooks are :class:`AppEvent.CloseRequestedEvent` (cancellable, the whole
    API is still alive) and :class:`AppEvent.ClosedEvent` (irreversible).
    """

    _instance: App | None = None

    def __init__(
        self,
        *,
        name: str = "lumiview",
        exit_on_last_window: bool = True,
        max_workers: int | None = 6,
        activation_policy: ActivationPolicy | None = None,
        app_id: str | None = None,
    ) -> None:
        if App._instance is not None:
            raise RuntimeError(
                "Only one App instance allowed per process. "
                "Use App.get() to access the existing instance."
            )

        if activation_policy is not None and sys.platform != "darwin":
            raise ValueError("activation_policy is macOS only")

        App._instance = self

        self._name = name
        self._exit_on_last_window = exit_on_last_window
        self._max_workers = max_workers
        self._activation_policy: ActivationPolicy | None = activation_policy
        self._app_id: str | None = app_id

        # Monotonic; written on the main thread only.
        self._state = AppState.CREATED
        # The committed exit code; written once, on the asyncio thread.
        self._exit_code = 0
        # An exit request was accepted and has not been prevented.
        self._exit_requested = threading.Event()

        self._event_loop: TaoEventLoop | None = None
        self._proxy: TaoEventLoopProxy | None = None

        self._main_tid: int | None = None

        self._cmd_queue: queue.Queue[_Command] = queue.Queue()
        self._pending: dict[str, Task[Any]] = {}
        # Wakes main-thread waits; predicate re-checks avoid lost wakeups.
        self._wake_cond = threading.Condition()

        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._async_ready: threading.Event = threading.Event()
        self._threadpool: ThreadPoolExecutor | None = None

        self._pending_lock = threading.Lock()
        self._handlers_lock = threading.Lock()

        self._handlers: dict[type[AppBaseEvent], list[_HandlerEntry]] = {}

        self._windows: dict[int, "Window"] = {}
        # Mutated on the main thread; the lock gives other threads a snapshot.
        self._windows_lock = threading.Lock()

        # Kept alive on the main thread (unsendable natives) + id → item table.
        self._menus: list[Any] = []
        self._menu_items: dict[str, Any] = {}

        self._trays: dict[str, Any] = {}

    @classmethod
    def get(cls) -> App:
        """Return the global App instance (raises if not yet created)."""
        if cls._instance is None:
            raise RuntimeError(
                "No App instance exists yet. Create one with App(name=...)."
            )
        return cls._instance

    @property
    def name(self) -> str:
        """The application name (as passed to :class:`App`)."""

        return self._name

    @property
    def state(self) -> AppState:
        """The current :class:`AppState` of the application."""

        return self._state

    @property
    def is_running(self) -> bool:
        """True while the app is ``RUNNING`` (the whole close phase included).

        It answers "is the native loop alive?", not "will new work be accepted?".
        """
        return self.state is AppState.RUNNING

    @property
    def is_stopped(self) -> bool:
        """True once the native loop has returned (``STOPPED``)."""
        return self.state is AppState.STOPPED

    @property
    def async_loop(self) -> asyncio.AbstractEventLoop | None:
        """The asyncio loop that runs user coroutines, or ``None`` before :meth:`run` and
        once the native loop returned. Owned by the app — never stop or close it.
        """
        if self.is_stopped:
            return None
        return self._async_loop

    @property
    def windows(self) -> tuple["Window", ...]:
        """A snapshot of the currently open windows (safe to iterate)."""
        with self._windows_lock:
            return tuple(self._windows.values())

    def get_window(self, win_id: int) -> "Window | None":
        """Return the open window with *win_id*, or ``None``."""
        with self._windows_lock:
            return self._windows.get(win_id)

    def is_async_thread(self) -> bool:
        """True if the caller is on the asyncio thread."""
        thread = self._async_thread
        return thread is not None and threading.get_ident() == thread.ident

    @main_thread
    def monitors(self) -> list[Monitor]:
        """All connected monitors.

        Call it from ``entry`` or a handler — the tao loop does not exist before
        :meth:`run`.
        """
        if self._event_loop is None:
            raise RuntimeError("App is not running — call App.run() first")
        return self._event_loop.available_monitors()

    @main_thread
    def primary_monitor(self) -> Monitor | None:
        """The primary monitor, or ``None`` when it cannot be determined."""
        if self._event_loop is None:
            raise RuntimeError("App is not running — call App.run() first")
        return self._event_loop.primary_monitor()

    def on(
        self,
        event: type[_E],
        handler: Callable[[_E], Any] | None = None,
        *,
        where: Callable[[_E], bool] | None = None,
    ) -> Subscription[_E]:
        """Register a handler for an app event class (sync or async).

        Pass *handler* to register it right away, or call the returned
        cancellable :class:`~lumiview.Subscription` (the decorator form).
        ``where`` runs inline during dispatch, so it must be synchronous.
        """
        sub = Subscription(self._handlers, event, where, self._handlers_lock)
        if handler is not None:
            sub(handler)
        return sub

    def wait_for(
        self,
        event: type[_E],
        *,
        where: Callable[[_E], bool] | None = None,
        timeout: float | None = None,
    ) -> Task[_E]:
        """Wait for the next app event of *event* that matches *where* (one-shot).

        Fails with ``AppClosedError`` when :class:`AppEvent.ClosedEvent` fires first, and
        with ``TimeoutError`` after *timeout*. Register it before the event can fire.
        """
        if self.is_stopped:
            return Task._failed(AppClosedError())
        return wait_for_event(
            self._handlers,
            event,
            where=where,
            timeout=timeout,
            lock=self._handlers_lock,
            close_event=AppEvent.ClosedEvent,
            is_closed=lambda: self.is_stopped,
            closed_error=AppClosedError,
        )

    def is_main_thread(self) -> bool:
        """True if the caller is on the tao / native GUI thread."""
        return threading.get_ident() == self._main_tid

    def call_on_main(
        self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> Task[T]:
        """Run *fn* on the main thread (inline when already there); returns a ``Task``.

        Fails with ``AppClosedError`` once the native loop has returned.
        """
        if self.is_stopped:
            return Task._failed(AppClosedError())
        if self.state is AppState.CREATED:
            # No loop to drain a queued command; fail instead of hanging.
            return Task._failed(
                RuntimeError("App is not running — call App.run() first")
            )

        if self.is_main_thread():
            try:
                return Task._done(fn(*args, **kwargs))
            except Exception as exc:
                return Task._failed(exc)

        handle: Task[T] = Task()
        self._enqueue(handle, fn, args, kwargs)
        return handle

    def _enqueue(
        self,
        handle: Task[T],
        fn: Callable[..., T],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        req_id = uuid.uuid4().hex
        # Register under the lock _finish swaps the dict with (no lost handle).
        with self._pending_lock:
            closed = self.is_stopped
            if not closed:
                self._pending[req_id] = handle
        if closed:
            # Settle outside the lock: callbacks may re-enter App.
            handle._settle(exc=AppClosedError())
            return
        try:
            self._cmd_queue.put((req_id, fn, args, kwargs))
            with self._wake_cond:
                self._wake_cond.notify_all()
            self._wake_main("wake")
        except Exception:
            # The loop can close between the check and the wake — settle here.
            with self._pending_lock:
                self._pending.pop(req_id, None)
            handle._settle(exc=AppClosedError())

    def _drain_commands(self) -> None:
        n = 0
        t0 = time.monotonic()
        while True:
            try:
                req_id, fn, args, kwargs = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            n += 1
            try:
                result = fn(*args, **kwargs)
                self._respond(req_id, result, None)
            except Exception as exc:
                self._respond(req_id, None, exc)
        if n:
            _log.debug("drained %d main-thread command(s) in %.1fms", n, fmt_ms(t0))

    def _respond(self, req_id: str, value: object, exc: BaseException | None) -> None:
        with self._pending_lock:
            handle = self._pending.pop(req_id, None)
        if handle is None:
            return
        if exc is not None:
            handle._settle(exc=exc)
        else:
            handle._settle(result=value)

    # Async scheduling (single choke point for "wake the loop")

    def _call_soon_threadsafe(self, fn: Callable[[], Any]) -> bool:
        """Schedule *fn* on the asyncio loop; ``False`` when the loop is missing or closed.

        Ignores the app state — the close phase still needs the loop.
        """
        loop = self._async_loop
        if loop is None:
            return False
        try:
            loop.call_soon_threadsafe(fn)
            return True
        except RuntimeError:
            return False

    def _spawn(
        self,
        coro: Coroutine,
        *,
        context: contextvars.Context | None = None,
    ) -> bool:
        """Schedule *coro* on the loop; close it and return ``False`` when that fails."""

        def _start() -> None:
            if context is None:
                asyncio.ensure_future(coro)
            else:
                context.run(asyncio.ensure_future, coro)

        if self._call_soon_threadsafe(_start):
            return True
        coro.close()
        return False

    def _emit(self, event: AppBaseEvent) -> "Task[None] | None":
        """Dispatch an app event; returns a completion ``Task`` or ``None``."""
        with self._handlers_lock:
            entries = list(self._handlers.get(type(event), ()))
        return _dispatch_event(self, entries, event)

    # Menu / tray events (GUI thread → asyncio loop)

    def _on_menu_event(self, event: Any) -> None:
        """Called on the GUI thread for every menu activation (the single
        muda global handler). Per-item callbacks run first, then the
        global event is emitted."""
        item = self._menu_items.get(event.id)
        ev = AppEvent.MenuItemActivatedEvent(id=event.id, menu_item=item)
        if item is not None:
            # Per-item callbacks first, in registration order (no `where`).
            _dispatch_event(
                self, [(fn, None) for fn in list(item._activate_callbacks)], ev
            )
        self._emit(ev)

    def _on_tray_event(self, event: Any) -> None:
        """Called on the GUI thread for tray icon events."""
        tray = self._trays.get(event.id)
        match event:
            case TrayIconClickEvent(
                id=tray_id,
                position=position,
                rect=rect,
                button=button,
                button_state=state,
            ):
                self._emit(
                    AppEvent.TrayIconClickEvent(
                        id=tray_id,
                        position=position,
                        rect=rect,
                        button=button,
                        button_state=state,
                        tray=tray,
                    )
                )

            case TrayIconDoubleClickEvent(
                id=tray_id, position=position, rect=rect, button=button
            ):
                self._emit(
                    AppEvent.TrayIconDoubleClickEvent(
                        id=tray_id,
                        position=position,
                        rect=rect,
                        button=button,
                        tray=tray,
                    )
                )

            case TrayIconEnterEvent(id=tray_id, position=position, rect=rect):
                self._emit(
                    AppEvent.TrayIconEnterEvent(
                        id=tray_id, position=position, rect=rect, tray=tray
                    )
                )

            case TrayIconMoveEvent(id=tray_id, position=position, rect=rect):
                self._emit(
                    AppEvent.TrayIconMoveEvent(
                        id=tray_id, position=position, rect=rect, tray=tray
                    )
                )

            case TrayIconLeaveEvent(id=tray_id, position=position, rect=rect):
                self._emit(
                    AppEvent.TrayIconLeaveEvent(
                        id=tray_id, position=position, rect=rect, tray=tray
                    )
                )

            case _:
                pass

    def run(
        self,
        entry: Callable[[], Any] | None = None,
    ) -> int:
        """Start the application; blocks the main thread until exit.

        Returns the exit code. ``entry`` may be sync or async and runs after every
        :class:`~lumiview.events.AppEvent.ReadyEvent` handler finished.
        """
        if self.state is not AppState.CREATED:
            raise RuntimeError(
                f"App already {'running' if self.state is AppState.RUNNING else 'finished'}. "
                "Cannot run() twice."
            )

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("App.run() must be called from the main thread")

        _log.info("App %r starting", self._name)

        self._main_tid = threading.get_ident()
        self._event_loop = TaoEventLoop(app_id=self._app_id)
        self._proxy = self._event_loop.create_proxy()
        self._threadpool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="lumiview-pool",
        )

        original_sigint = signal.getsignal(signal.SIGINT)

        # Pre-loop failures propagate; a crash inside the loop is logged.
        started = False
        try:
            # muda/tray-icon accept one callback each; the macOS policy and menu
            # bar must be installed before the loop consumes the EventLoop.
            set_loop_running(True)

            if self._activation_policy is not None:
                self._event_loop.set_activation_policy(self._activation_policy)

            init_menu_events(_menu_event_bridge)
            init_tray_events(_tray_event_bridge)

            if sys.platform == "darwin":
                try:
                    from lumiview.menu import Menu

                    Menu.default_app_menu().install_nsapp()
                except Exception:
                    _log.exception("Failed to install default macOS menu")

            signal.signal(signal.SIGINT, lambda *_: self._on_sigint())

            # RUNNING before the asyncio thread starts: entry must see it running.
            self._state = AppState.RUNNING
            _log.info("App %r running", self._name)

            self._async_thread = threading.Thread(
                target=self._run_asyncio,
                args=(entry,),
                daemon=True,
                name="lumiview-async",
            )
            self._async_thread.start()

            # _run_asyncio always signals, so this cannot hang.
            self._async_ready.wait()
            if self._async_loop is None:
                raise RuntimeError("Failed to start the asyncio thread")

            started = True
            self._event_loop.run(self._on_tao_event)
        except Exception:
            if not started:
                raise
            _log.exception("Event loop crashed")
        finally:
            self._finish(original_sigint)

        return self._exit_code

    def _on_sigint(self) -> None:
        """Request a graceful exit; a second Ctrl+C once the request is latched forces it.

        The latch is cleared again by ``prevent()``, so the next Ctrl+C negotiates
        instead of forcing.
        """
        if self._exit_requested.is_set():
            _log.warning("Ctrl+C during shutdown — forcing exit")
            self._wake_main("exit-now")
            return
        _log.info("Ctrl+C received, shutting down...")
        self.exit()

    def exit(self, code: int = 0) -> None:
        """Request a graceful shutdown; ``run()`` returns *code*.

        The first request wins. Close handlers run first and may cancel with
        ``event.prevent()``.
        """
        if not self.is_running or self._exit_requested.is_set():
            return
        if self._spawn(self._negotiate_exit(code)):
            return

        # No loop: record the request and leave now; _finish() still tears down.
        _log.warning("asyncio loop unavailable; the close handlers will not run")
        self._exit_requested.set()
        self._exit_code = code
        self._wake_main("exit-now")

    def _wake_main(self, cmd: str) -> None:
        """Post *cmd* to the native loop (any thread)."""
        try:
            if self._proxy is not None:
                self._proxy.send_event(json.dumps({"cmd": cmd}))
        except Exception:
            _log.exception("could not post %r to the native loop", cmd)

    # Close phase (asyncio thread) and teardown (main thread)

    async def _negotiate_exit(self, code: int) -> None:
        """Let the close handlers decide, then commit or cancel.

        Runs on the asyncio thread while everything is still alive. The request stays
        latched unless a handler prevents it; the commit point (where the exit code is
        recorded) only decides whether the native loop is asked to return.
        """
        if self._exit_requested.is_set() or not self.is_running:
            return

        self._exit_requested.set()
        t0 = time.monotonic()
        try:
            event = AppEvent.CloseRequestedEvent(exit_code=code)
            done = self._emit(event)
            if done is not None:
                await done
            if event.prevented:
                self._exit_requested.clear()
                _log.info("App %r shutdown prevented", self._name)
                return
            self._exit_code = code
            _log.info("App %r closing (code=%d)", self._name, code)
            self._wake_main("exit-now")
        except asyncio.CancelledError:
            _log.debug("close phase cancelled")
            raise
        except BaseException:
            _log.exception("Error during the close phase")
            # A crashing handler must not turn exit() into a no-op.
            self._exit_code = code
            self._wake_main("exit-now")
        finally:
            _log.debug("close phase finished in %.1fms", fmt_ms(t0))

    def _teardown_native(self) -> list[Task[None]]:
        """Release windows (dispatching ``ClosedEvent``), trays and menus, in that order.

        Idempotent; returns the dispatches so the caller can await them.
        """
        dispatches: list[Task[None]] = []
        for win in self.windows:
            try:
                win._release_native()
            except Exception:
                _log.exception("Error closing window")
            finally:
                try:
                    done = win._fail_closed()
                except Exception:
                    _log.exception("Error dispatching ClosedEvent")
                else:
                    if done is not None:
                        dispatches.append(done)

        with self._windows_lock:
            self._windows.clear()

        for objects, what in (
            (list(self._trays.values()), "tray icon"),
            (self._menus, "menu"),
            (list(self._menu_items.values()), "menu item"),
        ):
            for obj in objects:
                try:
                    obj._release_native()
                except Exception:
                    _log.exception("Error releasing %s", what)
        self._trays.clear()
        self._menus.clear()
        self._menu_items.clear()
        return dispatches

    def _finish(self, original_sigint: Any) -> None:
        """Tear down everything once the native loop returned (main thread).

        Each step is guarded so a second Ctrl+C cannot skip the rest.
        """
        try:
            signal.signal(signal.SIGINT, original_sigint)
        except Exception:
            _log.debug("could not restore the SIGINT handler", exc_info=True)

        # 1. Flip the state and take the pending handles atomically.
        with self._pending_lock:
            self._state = AppState.STOPPED
            pending, self._pending = self._pending, {}
        _log.info("App %r stopping", self._name)

        try:
            for handle in pending.values():
                handle._settle(exc=AppClosedError())
        except BaseException:
            _log.exception("Interrupted while failing pending handles")

        # 2. Tear down natively, then emit ClosedEvent while the loop is alive.
        try:
            dispatches = self._teardown_native()
            done = self._emit(AppEvent.ClosedEvent(exit_code=self._exit_code))
            if done is not None:
                dispatches.append(done)
            self._wait_dispatches(dispatches)
        except BaseException:
            _log.exception("Interrupted during teardown")

        # 3. Cancel the remaining tasks, let them unwind, close the loop.
        try:
            self._stop_async_loop()
        except BaseException:
            _log.exception("Interrupted during asyncio shutdown")

        # 4. Pool last: cancelled coroutines may still run finally blocks on it.
        if self._threadpool is not None:
            try:
                self._threadpool.shutdown(wait=False, cancel_futures=True)
            except BaseException:
                _log.exception("Interrupted while shutting down thread pool")

        set_loop_running(False)
        _log.info("App %r stopped", self._name)

    def _wait_dispatches(self, dispatches: list[Task[None]]) -> None:
        """Await the ``ClosedEvent`` dispatches (main thread, bounded)."""
        deadline = time.monotonic() + _TEARDOWN_TIMEOUT
        for done in dispatches:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _log.warning(
                    "close handlers did not finish within %.1fs",
                    _TEARDOWN_TIMEOUT,
                )
                return
            try:
                done.result(timeout=remaining)
            except KeyboardInterrupt:
                _log.warning("interrupted while waiting for close handlers")
            except BaseException:
                _log.exception("Close handler wait failed")

    def _stop_async_loop(self) -> None:
        """Cancel the remaining tasks, let them unwind, then stop and join the loop.

        ``cancel()`` needs the loop running — stopping it in the same step would drop
        every ``finally`` block.
        """
        loop, thread = self._async_loop, self._async_thread
        if loop is not None and loop.is_running():
            coro = self._finalize_loop()
            try:
                finalize = asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                coro.close()
            else:
                try:
                    finalize.result(timeout=_TEARDOWN_TIMEOUT)
                except BaseException:
                    _log.warning(
                        "asyncio shutdown did not finish within %.1fs",
                        _TEARDOWN_TIMEOUT,
                        exc_info=True,
                    )
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except RuntimeError:
                    pass

        if thread is not None:
            thread.join(timeout=_TEARDOWN_TIMEOUT)
            if thread.is_alive():
                _log.warning(
                    "asyncio thread did not exit within %.1fs",
                    _TEARDOWN_TIMEOUT,
                )

        self._async_loop = None

    async def _finalize_loop(self) -> None:
        """Cancel the remaining tasks and await their unwinding (runs on the loop)."""
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks(loop) if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await loop.shutdown_asyncgens()
        except Exception:
            _log.exception("shutdown_asyncgens() failed")

    @main_thread
    def hide(self) -> None:
        """Hide the whole application.

        macOS: native ``hide_application`` (Cmd+H). Elsewhere: hide every window.
        """
        if self._event_loop is None:
            return
        if sys.platform == "darwin":
            self._event_loop.hide_application()
            for win in self.windows:
                win._sync_webview_visibility_impl()
        else:
            for win in self.windows:
                win._hide_impl()

    @main_thread
    def show(self) -> None:
        """Show the application again (counterpart of :meth:`hide`)."""
        if self._event_loop is None:
            return
        if sys.platform == "darwin":
            self._event_loop.show_application()
            for win in self.windows:
                win._sync_webview_visibility_impl()
        else:
            for win in self.windows:
                win._show_impl()

    @main_thread
    def set_dock_visibility(self, visible: bool) -> None:
        """Show or hide the macOS Dock icon (macOS only)."""
        if sys.platform != "darwin":
            raise NotImplementedError("set_dock_visibility() is macOS only")
        if self._event_loop is None:
            return
        self._event_loop.set_dock_visibility(visible)

    def _run_asyncio(self, entry: Callable | None) -> None:

        async def _main() -> None:
            # Ready handlers finish before entry starts; a failing handler is only
            # logged (the remaining ones still run) and does not abort the startup.
            ready = self._emit(AppEvent.ReadyEvent())
            if ready is not None:
                await ready
            if entry is not None:
                try:
                    await run_async(entry)
                except Exception:
                    _log.exception("Error in entry point")
                    self.exit(1)

        try:
            self._async_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._async_loop)

            self._async_loop.create_task(_main())
        except BaseException:
            _log.exception("Failed to start the asyncio loop")
            return
        finally:
            self._async_ready.set()

        loop = self._async_loop
        try:
            loop.run_forever()
        except BaseException:
            _log.exception("Asyncio loop crashed")
        finally:
            # Close on the loop thread, right after run_forever returns.
            try:
                loop.close()
            except Exception:
                _log.exception("Failed to close the asyncio loop")
            asyncio.set_event_loop(None)

    def _register_window(self, window: "Window") -> None:
        """Register a fully created window (main thread)."""
        with self._windows_lock:
            self._windows[window._win_id] = window

    def _unregister_window(self, win_id: int) -> None:
        """Drop a window without applying the last-window exit policy."""
        with self._windows_lock:
            self._windows.pop(win_id, None)

    def _register_menu(self, menu: Any) -> None:
        """Keep a menu alive on the main thread (unsendable native object)."""
        self._menus.append(menu)

    def _register_menu_item(self, item: Any) -> None:
        """Register a menu item by id, warning on conflicting registrations."""
        prev = self._menu_items.get(item.id)
        if prev is not None and prev is not item:
            _log.warning("Duplicate menu item id %r — the newest wins", item.id)
        self._menu_items[item.id] = item

    def _register_tray(self, tray: Any) -> None:
        """Keep a tray icon alive on the main thread."""
        self._trays[tray.id] = tray

    def _unregister_tray(self, tray: Any) -> None:
        self._trays.pop(tray.id, None)

    def _remove_window(self, win_id: int) -> None:
        """Called when a Window is closed — clean up tracking."""
        _log.info("Window closed (id=%s)", win_id)
        with self._windows_lock:
            self._windows.pop(win_id, None)
            empty = not self._windows
        if self._exit_on_last_window and empty:
            self.exit()

    def _on_tao_event(self, event: TaoEvent) -> EventLoopControl | None:
        self._drain_commands()

        # Window-scoped events always carry an id; app events never do.
        if (wid := event.window_id) is not None:
            win = self.get_window(wid)
            if win is not None:
                win._on_tao_event(event)
            return EventLoopControl.Continue

        match event:
            case UserEvent(data=raw):
                cmd = json.loads(raw).get("cmd")
                if cmd == "exit-now":
                    # Close phase over (or forced): leave; _finish does the rest.
                    return EventLoopControl.Exit

            case ReopenEvent(has_visible_windows=visible):
                # macOS Dock reopen (fire-and-forget).
                self._emit(AppEvent.ReopenEvent(has_visible_windows=visible))

            case LoopDestroyedEvent():
                # macOS Cmd+Q / final exit: nothing can defer this; _finish does the rest.
                return EventLoopControl.Exit

            # App-scoped loop events (fire-and-forget).
            case OpenedEvent(urls=urls):
                self._emit(AppEvent.OpenedEvent(urls=urls))

            case DeviceAddedEvent():
                self._emit(AppEvent.DeviceAddedEvent())

            case DeviceRemovedEvent():
                self._emit(AppEvent.DeviceRemovedEvent())

            case DeviceMouseMotionEvent(dx=dx, dy=dy):
                self._emit(AppEvent.DeviceMouseMotionEvent(dx=dx, dy=dy))

            case DeviceMouseWheelEvent(delta_kind=kind, dx=dx, dy=dy):
                self._emit(
                    AppEvent.DeviceMouseWheelEvent(delta_kind=kind, dx=dx, dy=dy)
                )

            case DeviceMotionEvent(axis=axis, value=value):
                self._emit(AppEvent.DeviceMotionEvent(axis=axis, value=value))

            case DeviceButtonEvent(button=button, state=state):
                self._emit(AppEvent.DeviceButtonEvent(button=button, state=state))

            case DeviceKeyEvent(physical_key=key, state=state):
                self._emit(AppEvent.DeviceKeyEvent(physical_key=key, state=state))

            case DeviceTextEvent(codepoint=codepoint):
                self._emit(AppEvent.DeviceTextEvent(codepoint=codepoint))

            case _:
                pass

        return EventLoopControl.Continue


class AppClosedError(RuntimeError):
    """Raised when an operation is attempted after the app has closed."""

    def __init__(self) -> None:
        super().__init__(f"lumiview app has been closed")


class WindowClosedError(RuntimeError):
    """Raised when an operation is attempted on a closed window."""

    def __init__(self, win_id: int | None = None) -> None:
        msg = "Window has been closed"
        if win_id is not None:
            msg += f" (id={win_id})"
        super().__init__(msg)


# Module level (the Rust OnceLock keeps a strong reference): no closure
# over a specific App; both run on the GUI thread.


def _menu_event_bridge(event: Any) -> None:
    """Forward a native menu activation to the current App (GUI thread)."""
    try:
        App.get()._on_menu_event(event)
    except Exception:
        _log.exception("menu event dispatch failed")


def _tray_event_bridge(event: Any) -> None:
    """Forward a native tray event to the current App (GUI thread)."""
    try:
        App.get()._on_tray_event(event)
    except Exception:
        _log.exception("tray event dispatch failed")
