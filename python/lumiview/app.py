from __future__ import annotations

import asyncio
import contextvars
import inspect
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
    MainEventsClearedEvent,
    Monitor,
    NewEventsEvent,
    OpenedEvent,
    RedrawEventsClearedEvent,
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
    fn_name,
    fmt_ms,
    main_thread,
    passes_where,
    wait_for_event,
)

P = ParamSpec("P")
T = TypeVar("T")
_E = TypeVar("_E", bound=AppBaseEvent)

_Handler = Callable[..., Any]
_HandlerEntry = tuple[_Handler, Callable[[Any], bool] | None]
_Command = tuple[str, Callable, tuple, dict[str, Any]]

_log = logging.getLogger("lumiview.app")

# Overall budget for the exit cleanup sequence in run()'s finally block.
_SHUTDOWN_TIMEOUT = 5

if TYPE_CHECKING:
    from lumiview import Window


class AppState(Enum):
    CREATED = auto()  # Configuring, handlers registered
    STARTING = auto()  # Creating Tao event loop, starting scheduler
    RUNNING = auto()  # Window/WebView operations allowed
    STOPPING = auto()  # Rejecting new tasks, closing windows
    STOPPED = auto()  # Resources released


class App:
    """Desktop application.

    Create one instance, configure it, then call :meth:`run`.

    Parameters:
        name: Application name (used for platform-specific identity).
        exit_on_last_window: If True (default), exit when the last window closes.
           Set to False for tray-based apps.
        max_workers: Thread pool size for sync :func:`~lumiview.task.task`
           calls.
        activation_policy: macOS only — the app activation policy
           (e.g. ``Accessory`` for menu-bar/agent apps without a Dock
           icon). Must be set before :meth:`run`; passing it on another
           platform raises ``ValueError``.
        app_id: Linux only — the GTK application id (application
           uniqueness and desktop integration on Wayland). Ignored on
           other platforms.

    Lifecycle: register an entry via :meth:`run` (main flow) and/or
    observe via :meth:`on` with :class:`AppEvent.ReadyEvent`. Request
    exit with :meth:`exit`; cleanup code goes in
    ``app.on(AppEvent.AppCloseEvent)`` handlers (awaited during
    shutdown).
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

        # Configuration
        self._name = name
        self._exit_on_last_window = exit_on_last_window
        self._max_workers = max_workers
        self._activation_policy: ActivationPolicy | None = activation_policy
        self._app_id: str | None = app_id

        # State
        self._state = AppState.CREATED
        # None = exit not requested yet; the first request wins. Kept
        # separate from _state so "exit requested" (a promise) is not
        # conflated with "cleanup executed" (STOPPING).
        self._exit_code: int | None = None

        # Rust bindings (created in run())
        self._event_loop: TaoEventLoop | None = None
        self._proxy: TaoEventLoopProxy | None = None

        # Thread identity
        self._main_tid: int | None = None

        # Command queue (any thread → main thread)
        self._cmd_queue: queue.Queue[_Command] = queue.Queue()
        self._pending: dict[str, Task[Any]] = {}
        # Wake signal for main-thread waits: notified when a command is
        # enqueued and when a dispatched task completes. Waits use
        # Condition.wait_for with a predicate, so lost-wakeup races are
        # re-checked instead of hanging.
        self._wake_cond = threading.Condition()

        # Async infrastructure
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._async_ready: threading.Event = threading.Event()
        self._threadpool: ThreadPoolExecutor | None = None

        # Synchronization for state shared with worker/asyncio threads.
        # The GIL only made single bytecodes atomic; the free-threaded build
        # removes even that serialization, so compound operations need locks.
        self._pending_lock = threading.Lock()
        self._handlers_lock = threading.Lock()
        self._exit_lock = threading.Lock()
        # Set as soon as shutdown is requested; rejects new cross-thread work
        # before the tao loop reaches _handle_exit_event.
        self._closing = False

        # Event handlers
        self._handlers: dict[type[AppBaseEvent], list[_HandlerEntry]] = {}

        # Windows
        self._windows: dict[int, Window] = {}
        # _windows is mutated on the main thread only; the reader lock lets
        # other threads take a consistent snapshot (free-threaded builds do
        # not guarantee that dict iteration survives concurrent mutation).
        self._windows_lock = threading.Lock()

        # Menus: roots registered on the main thread (kept alive here so
        # unsendable native objects only drop on the main thread) and the
        # id → item table used to resolve activation events.
        self._menus: list[Any] = []
        self._menu_items: dict[str, Any] = {}

        # Tray icons: id → TrayIcon (main-thread owned; multiple allowed).
        self._trays: dict[str, Any] = {}

        # Shutdown dispatches (window ClosedEvent + AppCloseEvent),
        # awaited in run()'s finally so waiters and Close handlers
        # actually run before the asyncio loop stops.
        self._close_tasks: list[Task[None]] = []

    @staticmethod
    def _check_activation_policy(policy: ActivationPolicy | None) -> None:
        """Reject ``activation_policy`` outside macOS before any state exists."""
        if policy is not None and sys.platform != "darwin":
            raise ValueError("activation_policy is macOS only")

    # Singleton access

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

    # Public introspection

    @property
    def is_exit(self) -> bool:
        """True if the app is exiting (after :meth:`exit` or window close)."""
        return self._closing or self._state in (AppState.STOPPING, AppState.STOPPED)

    @property
    def async_loop(self) -> asyncio.AbstractEventLoop | None:
        """The asyncio loop that runs user coroutines, or ``None``.

        ``None`` before :meth:`run` starts and once shutdown begins, so
        third-party threads can hand it to
        ``asyncio.run_coroutine_threadsafe`` without racing a dead loop.
        The loop is owned by the app — never call ``stop()`` / ``close()``
        on it.
        """
        if self.is_exit:
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

        Call it from ``entry`` (or any handler) before creating the first
        window to size/center that window — the tao event loop does not
        exist before ``App.run()``.
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

    # Event handlers

    def on(
        self,
        event: type[_E],
        *,
        where: Callable[[_E], bool] | None = None,
    ) -> Subscription:
        """Register a handler for an app event class.

        ``app.on(AppEvent.ReadyEvent)(handler)`` — the handler receives
        the event object. Can be sync or async — auto-detected. Runs on
        the asyncio loop (NOT the GUI thread).

        *where* is a filter function — the event class binds its parameter
        type, so a mistyped field is a static error::

            app.on(
                AppEvent.MenuItemActivatedEvent,
                where=lambda e: e.id == "quit",
            )(on_quit)

        Parameters:
            event: The :class:`AppBaseEvent` subclass to handle.
            where: Optional filter function ``(event) -> bool``; only
                matching events reach the handler. Runs inline during
                dispatch, so it must be synchronous.
        """
        return Subscription(self._handlers, event, where, self._handlers_lock)

    def wait_for(
        self,
        event: type[_E],
        *,
        where: Callable[[_E], bool] | None = None,
        timeout: float | None = None,
    ) -> Task[_E]:
        """Wait for the next app event of *event* that matches *where*.

        One-shot: the returned :class:`~lumiview.task.Task` resolves with
        the event and the temporary handler is removed. Must be registered
        before the event fires — call it from ``entry`` or a
        :class:`~lumiview.events.AppEvent.ReadyEvent` handler::

            async def entry():
                closed = app.wait_for(AppEvent.AppCloseEvent)
                app.exit(0)
                await closed

        The task fails with :class:`AppClosedError` if the app shuts down
        first, and with :class:`TimeoutError` when *timeout* seconds
        elapse. Like :meth:`on`, the temporary handler runs on the asyncio
        loop (NOT the GUI thread).
        """
        if self.is_exit:
            return Task._failed(AppClosedError())
        return wait_for_event(
            self._handlers,
            event,
            where=where,
            timeout=timeout,
            lock=self._handlers_lock,
            close_event=AppEvent.AppCloseEvent,
            is_closed=lambda: self.is_exit,
            closed_error=lambda: AppClosedError()
        )

    # Bridge: any thread → main thread

    def is_main_thread(self) -> bool:
        """True if the caller is on the tao / native GUI thread."""
        return threading.get_ident() == self._main_tid

    def call_on_main(
        self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> Task[T]:
        """Run *fn* on the main thread, return a :class:`Task`.

        On the main thread, executes directly. Otherwise queues the call.

        Use ``await handle`` from asyncio, or ``handle.result()`` from
        any other thread.
        """
        if self.is_exit:
            return Task._failed(AppClosedError())
        if self._state == AppState.CREATED:
            # Not running yet — a queued command would never be consumed
            # (no tao loop, no proxy wake) and the handle would hang
            # silently. Mirrors the not-running behavior of
            # _submit_async/_submit_sync.
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
        # Register and check the closing flag under one lock: the shutdown
        # sweep swaps the whole dict out, so a handle can never be inserted
        # between its snapshot and clear() and then silently dropped.
        with self._pending_lock:
            closing = self._closing
            if not closing:
                self._pending[req_id] = handle
        if closing:
            # Settle outside the lock: Future callbacks run synchronously
            # and may call back into App.
            if not handle.done():
                handle.set_exception(AppClosedError())
            return
        try:
            self._cmd_queue.put((req_id, fn, args, kwargs))
            with self._wake_cond:
                self._wake_cond.notify_all()
            proxy = self._proxy
            if proxy is not None:
                proxy.send_event(json.dumps({"cmd": "wake", "id": req_id}))
        except Exception:
            # The event loop can close between the admission check and the
            # wake-up. Settle the handle here instead of leaving it pending
            # forever (and never leak the exception to the caller thread).
            with self._pending_lock:
                self._pending.pop(req_id, None)
            if not handle.done():
                handle.set_exception(AppClosedError())

    # Main-thread command processing

    def _drain_commands(self) -> None:
        n = 0
        t0 = time.monotonic()
        while not self._cmd_queue.empty():
            req_id, fn, args, kwargs = self._cmd_queue.get_nowait()
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
        if handle is None or handle.cancelled():
            return
        if exc is not None:
            handle.set_exception(exc)
        else:
            handle.set_result(value)

    # Async scheduling (single choke point for "wake the loop")

    def _call_soon_threadsafe(self, fn: Callable[[], Any]) -> bool:
        """Schedule *fn* on the asyncio loop.

        Returns ``False`` when the loop is missing or already closed, so
        callers can settle their own Task / response instead of racing a
        dead loop. Deliberately ignores ``_closing``: shutdown still needs
        the loop to dispatch cleanup handlers.
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
        """Schedule *coro* on the asyncio loop; close it when that fails.

        *context* (from :func:`contextvars.copy_context`) makes the new task
        inherit the caller's contextvars; used by :func:`lumiview.task.task`.
        """

        def _start() -> None:
            if context is None:
                asyncio.ensure_future(coro)
            else:
                context.run(asyncio.ensure_future, coro)

        if self._call_soon_threadsafe(_start):
            return True
        coro.close()
        return False

    # Event dispatch (internal)

    def _dispatch_handlers(
        self,
        handlers: list[_HandlerEntry],
        event: AppBaseEvent,
        *,
        stop_on_error: bool = False,
    ) -> "Task[None] | None":
        """Run *handlers* for *event* on the asyncio loop.

        Each handler is a ``(callback, where)`` pair; pairs whose
        filter does not match are skipped.

        Returns a completion signal (a :class:`Task` resolved when all
        handlers finish) or None when there is no loop or no handlers.
        Shared by :meth:`_emit` and the per-item menu activation
        callbacks.
        """
        loop = self._async_loop
        if loop is None or not handlers:
            return None

        matched: list[_Handler] = [
            fn for fn, where in handlers if passes_where(where, event)
        ]

        if not matched:
            return None

        _log.debug(
            "dispatching %s to %d handler(s): %s",
            type(event).__name__,
            len(matched),
            ", ".join(fn_name(h) for h in matched),
        )
        done: Task[None] = Task()

        async def _dispatch() -> None:
            first_exc: BaseException | None = None
            for fn in matched:
                try:
                    await run_async(fn, event)
                except BaseException as exc:
                    _log.exception(f"Error in {type(event).__name__} handler: {fn}")
                    if stop_on_error:
                        first_exc = exc
                        break
            if first_exc is not None:
                done.set_exception(first_exc)
            else:
                done.set_result(None)

        if not self._call_soon_threadsafe(lambda: asyncio.create_task(_dispatch())):
            # Loop closed during shutdown: no handler will run, but the
            # caller still needs a settled completion signal.
            done.set_result(None)
        return done

    def _emit(
        self, event: AppBaseEvent, *, stop_on_error: bool = False
    ) -> "Task[None] | None":
        """Dispatch an app event to registered handlers on the asyncio loop.

        Returns a completion signal (a :class:`Task` resolved when all
        handlers finish) or None when there is no loop or no handlers.
        Callers
        that don't need to wait may ignore the return value — only
        ``_handle_exit_event`` consumes it.
        """
        with self._handlers_lock:
            entries = list(self._handlers.get(type(event), ()))
        return self._dispatch_handlers(entries, event, stop_on_error=stop_on_error)

    # Menu / tray events (GUI thread → asyncio loop)

    def _on_menu_event(self, event: Any) -> None:
        """Called on the GUI thread for every menu activation (the single
        muda global handler). Per-item callbacks run first, then the
        global event is emitted."""
        item = self._menu_items.get(event.id)
        ev = AppEvent.MenuItemActivatedEvent(id=event.id, menu_item=item)
        if item is not None:
            # Resolve the item's own on_activate callbacks on the asyncio
            # loop, in registration order. They carry no `where`
            # predicate, so pair them with None for the shared dispatcher.
            self._dispatch_handlers(
                [(fn, None) for fn in list(item._activate_callbacks)], ev
            )
        self._emit(ev)

    def _on_tray_event(self, event: Any) -> None:
        """Called on the GUI thread for tray icon events."""
        tray = self._trays.get(event.id)
        if isinstance(event, TrayIconClickEvent):
            self._emit(
                AppEvent.TrayIconClickEvent(
                    id=event.id,
                    position=event.position,
                    rect=event.rect,
                    button=event.button,
                    button_state=event.button_state,
                    tray=tray,
                )
            )
        elif isinstance(event, TrayIconDoubleClickEvent):
            self._emit(
                AppEvent.TrayIconDoubleClickEvent(
                    id=event.id,
                    position=event.position,
                    rect=event.rect,
                    button=event.button,
                    tray=tray,
                )
            )
        elif isinstance(event, TrayIconEnterEvent):
            self._emit(
                AppEvent.TrayIconEnterEvent(
                    id=event.id, position=event.position, rect=event.rect, tray=tray
                )
            )
        elif isinstance(event, TrayIconMoveEvent):
            self._emit(
                AppEvent.TrayIconMoveEvent(
                    id=event.id, position=event.position, rect=event.rect, tray=tray
                )
            )
        elif isinstance(event, TrayIconLeaveEvent):
            self._emit(
                AppEvent.TrayIconLeaveEvent(
                    id=event.id, position=event.position, rect=event.rect, tray=tray
                )
            )

    # Run loop

    def run(
        self,
        entry: Callable[[], Any] | None = None,
    ) -> int:
        """Start the application. Blocks until exit.

        Must be called from the main thread; create windows inside
        *entry* (or in :class:`AppEvent.ReadyEvent` handlers).

        Parameters:
            entry: An async or sync function to call once the app is ready.

        Returns:
            Exit code (0 for normal exit).
        """
        if self._state != AppState.CREATED:
            raise RuntimeError(
                f"App already {'running' if self._state == AppState.RUNNING else 'finished'}. "
                "Cannot run() twice."
            )

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("App.run() must be called from the main thread")

        self._state = AppState.STARTING
        _log.info("App %r starting", self._name)

        self._event_loop = TaoEventLoop(app_id=self._app_id)
        self._proxy = self._event_loop.create_proxy()
        self._main_tid = threading.get_ident()

        self._threadpool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="lumiview-pool",
        )

        # Menus and trays: mark the loop as running (the construction
        # guard checked by TaoMenu/TaoTrayIcon), register the single
        # per-process event callbacks (muda and tray-icon accept exactly
        # one handler each), apply the macOS activation policy before the
        # loop consumes the EventLoop, and install the default macOS menu
        # bar (Application/Edit/Window — replaceable via
        # ``await menu.install_nsapp()``).
        set_loop_running(True)

        if self._activation_policy is not None:
            # Validated in __init__ — this branch is macOS-only by construction.
            self._event_loop.set_activation_policy(self._activation_policy)

        init_menu_events(_menu_event_bridge)
        init_tray_events(_tray_event_bridge)

        if sys.platform == "darwin":
            try:
                from lumiview.menu import Menu

                Menu.default_app_menu().install_nsapp()
            except Exception:
                _log.exception("Failed to install default macOS menu")

        # Install Ctrl+C handler. signal.signal() only works on the
        # main thread — background-thread runs (e.g. future test
        # harness) skip it.
        def _sigint_handler(signum, frame):
            self._on_sigint()

        original_sigint = signal.getsignal(signal.SIGINT)

        signal.signal(signal.SIGINT, _sigint_handler)

        self._async_thread = threading.Thread(
            target=self._run_asyncio,
            args=(entry,),
            daemon=True,
            name="lumiview-async",
        )
        self._async_thread.start()

        try:
            # Wait for the asyncio loop to be ready. _run_asyncio always
            # signals the event (also on startup failure), so this cannot
            # hang; a failed startup is reported below.
            self._async_ready.wait()
            if self._async_loop is None:
                raise RuntimeError("Failed to start the asyncio thread")

            self._state = AppState.RUNNING
            _log.info("App %r running", self._name)

            # Run the Tao event loop (blocks main thread).
            self._event_loop.run(self._on_tao_event)
        except Exception:
            _log.exception("Event loop crashed")
        finally:
            self._state = AppState.STOPPED
            _log.info("App %r stopped", self._name)

            signal.signal(signal.SIGINT, original_sigint)

            # Wait for the shutdown dispatches (window ClosedEvent, then
            # AppCloseEvent) before stopping the asyncio loop, so waiters
            # and Close handlers actually run.
            for done in self._close_tasks:
                try:
                    done.result()
                except KeyboardInterrupt:
                    _log.warning("interrupted while waiting for Close handlers")
                except BaseException:
                    _log.exception("Close handler wait failed")

            # Each cleanup step below is individually guarded: a second
            # Ctrl+C (KeyboardInterrupt — the original handler is already
            # restored) must not skip the remaining steps, so run() still
            # returns cleanly and no handle is left hanging.
            # 1. Cancel pending asyncio tasks so hung awaits fail fast
            #    with CancelledError, then stop the loop. asyncio objects
            #    are not thread-safe, so the whole pass runs on the loop
            #    thread via call_soon_threadsafe — doing it here would
            #    race task creation and, on error, could skip loop.stop().
            try:
                loop = self._async_loop
                if loop is not None:

                    def _cancel_and_stop() -> None:
                        for task in asyncio.all_tasks(loop):
                            task.cancel()
                        loop.stop()

                    try:
                        loop.call_soon_threadsafe(_cancel_and_stop)
                    except RuntimeError:
                        _log.debug("asyncio loop already closed")
                if self._async_thread is not None:
                    self._async_thread.join(timeout=_SHUTDOWN_TIMEOUT)
                    if self._async_thread.is_alive():
                        _log.warning(
                            f"async thread did not exit within remaining budget ({_SHUTDOWN_TIMEOUT}s)"
                        )
            except BaseException:
                _log.exception("Interrupted during asyncio shutdown")

            # 2. Fail pending main-thread command handles. After the
            #    event loop returns, the main thread no longer drains
            #    the command queue — these would otherwise hang forever.
            #    Swap the dict out under the lock: a concurrent _enqueue
            #    either lands before the swap (and is failed here) or
            #    sees _closing and fails its own handle.
            try:
                with self._pending_lock:
                    self._closing = True
                    pending, self._pending = self._pending, {}
                for handle in pending.values():
                    if not handle.done():
                        handle.set_exception(AppClosedError())
            except BaseException:
                _log.exception("Interrupted while failing pending handles")

            # 3. Thread pool: cancel queued (not yet started) work.
            #    Tasks already running on pool threads cannot be
            #    interrupted — documented limitation.
            if self._threadpool is not None:
                try:
                    self._threadpool.shutdown(wait=False, cancel_futures=True)
                except BaseException:
                    _log.exception("Interrupted while shutting down thread pool")

            set_loop_running(False)

        return self._exit_code if self._exit_code is not None else 0

    def _on_sigint(self) -> None:
        """Handle SIGINT without taking any app lock.

        Signal handlers run on the main thread, which may be inside a
        ``_pending_lock`` / ``_exit_lock`` critical section when the signal
        arrives — :meth:`exit` acquires both, so calling it here would
        self-deadlock the GUI thread (``threading.Lock`` is not reentrant).
        Hand the request to the asyncio loop instead, and fall back to the
        tao proxy when the loop is already gone.
        """
        _log.info("Ctrl+C received, shutting down...")
        loop = self._async_loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self.exit)
                return
            except RuntimeError:
                _log.debug("asyncio loop already closed during SIGINT")
        proxy = self._proxy
        if proxy is not None:
            try:
                proxy.send_event(json.dumps({"cmd": "exit"}))
            except Exception:
                pass

    def exit(self, code: int = 0) -> None:
        """Request a graceful shutdown; ``run()`` returns *code*.

        Only records the request (first request wins) and wakes the
        main thread — it does **not** transition the state. The actual
        cleanup (closing windows, emitting :class:`AppCloseEvent`) runs
        when the exit event is handled on the main thread, so
        ``_handle_exit_event`` remains the single transition into
        STOPPING.
        """
        with self._exit_lock:
            if self._exit_code is not None:
                # Already requested — ignore so the first requested exit
                # code wins. A window closing mid-shutdown (_remove_window,
                # code 0) can no longer overwrite an explicit exit(code).
                return
            if self._state == AppState.CREATED:
                # Not running yet — nothing to shut down. Ignore the request,
                # or run() would later misreport "App already finished".
                return
            self._exit_code = code

        # Stop admitting cross-thread work immediately: the tao thread may
        # take several more turns to reach _handle_exit_event, and anything
        # queued in that window would never be drained.
        with self._pending_lock:
            self._closing = True

        proxy = self._proxy
        if proxy is not None:
            try:
                proxy.send_event(json.dumps({"cmd": "exit"}))
            except Exception:
                pass

    # App-level visibility (main thread; returns Task)

    @main_thread
    def hide(self) -> None:
        """Hide the entire application.

        - macOS: hides the whole application (all windows, app removed
          from the switcher) — the native ``hide_application``, Cmd+H.
        - Other platforms: hides every open window (there is no
          platform "hide app" concept there).

        Use :meth:`show` to bring it back. Returns a :class:`Task`.
        """
        if self._event_loop is None:
            return
        if sys.platform == "darwin":
            self._event_loop.hide_application()
            for win in self.windows:
                win._sync_webview_visibility()
        else:
            for win in self.windows:
                win.hide()

    @main_thread
    def show(self) -> None:
        """Show the entire application again (counterpart of :meth:`hide`).

        - macOS: shows the whole application (native ``show_application``).
        - Other platforms: shows every open window.

        Returns a :class:`Task`.
        """
        if self._event_loop is None:
            return
        if sys.platform == "darwin":
            self._event_loop.show_application()
            for win in self.windows:
                win._sync_webview_visibility()
        else:
            for win in self.windows:
                win.show()

    @main_thread
    def set_dock_visibility(self, visible: bool) -> None:
        """Show (``True``) or hide (``False``) the macOS Dock icon.

        Combined with ``App(activation_policy=ActivationPolicy.Accessory)``
        this makes a menu-bar/tray application. **macOS only** — raises
        :class:`NotImplementedError` elsewhere.
        """
        if sys.platform != "darwin":
            raise NotImplementedError("set_dock_visibility() is macOS only")
        if self._event_loop is None:
            return
        self._event_loop.set_dock_visibility(visible)

    def _run_asyncio(self, entry: Callable | None) -> None:

        async def _main() -> None:
            ready = self._emit(AppEvent.ReadyEvent(), stop_on_error=True)
            if ready is not None:
                ready.on_exception(self._on_ready_failed)
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

        try:
            self._async_loop.run_forever()
        except BaseException:
            _log.exception("Asyncio loop crashed")

    def _on_ready_failed(self, exc: BaseException) -> None:
        """A ReadyEvent handler crashed — the startup failed, exit non-zero."""
        if exc is not None:
            _log.error("Error in ReadyEvent handler: %s", exc, exc_info=exc)
            self.exit(1)

    # Window tracking

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

    # Tao event callback

    def _on_tao_event(self, event: TaoEvent) -> EventLoopControl | None:
        self._drain_commands()

        if isinstance(event, UserEvent):
            data = json.loads(event.data)
            cmd = data.get("cmd")
            if cmd == "exit":
                return self._handle_exit_event()
            elif cmd == "wake":
                pass  # just woke us to drain commands
            return EventLoopControl.Continue

        if isinstance(event, ReopenEvent):
            # macOS Dock reopen — app-scoped, not tied to a window.
            # Fire-and-forget: handlers restore/create windows as they see fit.
            self._emit(
                AppEvent.ReopenEvent(has_visible_windows=event.has_visible_windows)
            )
            return EventLoopControl.Continue

        if isinstance(event, LoopDestroyedEvent):
            # The event loop is stopping. On macOS this is the only
            # signal for Cmd+Q / app termination (tao does not intercept
            # `applicationWillTerminate`, so windows never see a
            # CloseRequested) — run the graceful shutdown so
            # AppCloseEvent handlers actually execute. Idempotent via
            # _handle_exit_event's state check.
            return self._handle_exit_event()

        # App-scoped loop events (window_id is None). Fire-and-forget:
        # the per-frame events (NewEvents/MainEventsCleared/
        # RedrawEventsCleared) only reach handlers if one is registered.
        if isinstance(event, NewEventsEvent):
            self._emit(AppEvent.NewEventsEvent(cause=event.cause))
            return EventLoopControl.Continue

        if isinstance(event, MainEventsClearedEvent):
            self._emit(AppEvent.MainEventsClearedEvent())
            return EventLoopControl.Continue

        if isinstance(event, RedrawEventsClearedEvent):
            self._emit(AppEvent.RedrawEventsClearedEvent())
            return EventLoopControl.Continue

        if isinstance(event, OpenedEvent):
            self._emit(AppEvent.OpenedEvent(urls=event.urls))
            return EventLoopControl.Continue

        if isinstance(event, DeviceAddedEvent):
            self._emit(AppEvent.DeviceAddedEvent())
            return EventLoopControl.Continue

        if isinstance(event, DeviceRemovedEvent):
            self._emit(AppEvent.DeviceRemovedEvent())
            return EventLoopControl.Continue

        if isinstance(event, DeviceMouseMotionEvent):
            self._emit(AppEvent.DeviceMouseMotionEvent(dx=event.dx, dy=event.dy))
            return EventLoopControl.Continue

        if isinstance(event, DeviceMouseWheelEvent):
            self._emit(
                AppEvent.DeviceMouseWheelEvent(
                    delta_kind=event.delta_kind, dx=event.dx, dy=event.dy
                )
            )
            return EventLoopControl.Continue

        if isinstance(event, DeviceMotionEvent):
            self._emit(AppEvent.DeviceMotionEvent(axis=event.axis, value=event.value))
            return EventLoopControl.Continue

        if isinstance(event, DeviceButtonEvent):
            self._emit(
                AppEvent.DeviceButtonEvent(button=event.button, state=event.state)
            )
            return EventLoopControl.Continue

        if isinstance(event, DeviceKeyEvent):
            self._emit(
                AppEvent.DeviceKeyEvent(
                    physical_key=event.physical_key, state=event.state
                )
            )
            return EventLoopControl.Continue

        if isinstance(event, DeviceTextEvent):
            self._emit(AppEvent.DeviceTextEvent(codepoint=event.codepoint))
            return EventLoopControl.Continue

        # Every other tao event is window-scoped — route it to the window.
        if (wid := event.window_id) is not None:
            win = self.get_window(wid)
            if win is not None:
                win._on_tao_event(event)

        return EventLoopControl.Continue

    def _handle_exit_event(self) -> EventLoopControl:
        """Graceful shutdown sequence.

        Single transition into STOPPING: ``exit()`` only records the
        request, so this runs the real cleanup (closing windows,
        emitting AppCloseEvent) on every exit path — explicit exit(),
        Ctrl+C, last-window close, and LoopDestroyed alike.
        """
        if self._state == AppState.STOPPING:
            # Already shutting down — a second trigger (e.g.
            # LoopDestroyed following an exit() request, or a window
            # closing mid-cleanup) must not re-run handlers or re-emit
            # AppCloseEvent.
            return EventLoopControl.Exit
        self._state = AppState.STOPPING
        with self._pending_lock:
            self._closing = True

        close_tasks: list[Task[None]] = []

        for win in self.windows:
            try:
                win._release_native()
            except Exception:
                _log.exception("Error closing window")
            finally:
                # Emit ClosedEvent for pending wait_for / wait_loaded
                # waiters; the dispatch is awaited in run()'s finally.
                try:
                    done = win._fail_closed()
                except Exception:
                    _log.exception("Error dispatching ClosedEvent")
                else:
                    if done is not None:
                        close_tasks.append(done)

        with self._windows_lock:
            self._windows.clear()

        # Menus and trays: release native handles here, on the main thread
        # (unsendable objects may only drop on this thread). Trays first —
        # a tray may hold Arc references into a menu tree; detaching the
        # subclassed window before the menu drops is the safe order on
        # Windows. Each object owns its own teardown; only the order lives
        # here.
        for tray in list(self._trays.values()):
            try:
                tray._release_native()
            except Exception:
                _log.exception("Error closing tray icon")
        self._trays.clear()

        for menu in self._menus:
            try:
                menu._release_native()
            except Exception:
                _log.exception("Error releasing menu")
        for item in self._menu_items.values():
            try:
                item._release_native()
            except Exception:
                _log.exception("Error releasing menu item")
        self._menus.clear()
        self._menu_items.clear()

        # Emit Close for remaining handlers. The dispatches are awaited in
        # run()'s finally block before the asyncio loop stops, so cleanup
        # handlers and pending waiters actually run.
        app_close = self._emit(AppEvent.AppCloseEvent())
        if app_close is not None:
            close_tasks.append(app_close)
        self._close_tasks = close_tasks

        return EventLoopControl.Exit


# Error types


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


# Event bridges (module level — held by the Rust OnceLock callbacks)
#
# Registered once by App.run() in its STARTING phase; the Rust side keeps
# a strong Py reference, so these must not close over a specific App
# instance. Both run on the GUI thread (muda/tray-icon fire their events
# there), where the GIL is released while the tao loop drains — calling
# back into Python cannot deadlock.


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
