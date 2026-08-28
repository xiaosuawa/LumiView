from __future__ import annotations

import asyncio
import inspect
import json
import logging
import queue
import signal
import sys
import threading
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
    NewEventsEvent,
    OpenedEvent,
    RedrawEventsClearedEvent,
    ReopenEvent,
    TaoEvent,
    TaoEventLoop,
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
from lumiview.utils import main_thread

P = ParamSpec("P")
T = TypeVar("T")
F = TypeVar("F", bound=Callable)

_Handler = Callable[..., Any]
_Command = tuple[str, Callable, tuple, dict[str, Any]]

log = logging.getLogger("lumiview.app")

# tao/GUI thread identity for Task blocking adaptation. Assigned by
# App.run() and reset on exit. Lives in this module because _task's
# Task._block() reads it via deferred import — a by-value import
# would freeze it at None.
_GUI_THREAD_ID: int | None = None

# Overall budget for the exit cleanup sequence in run()'s finally block.
_SHUTDOWN_TIMEOUT = 5

if TYPE_CHECKING:
    from lumiview import Window


class AppState(Enum):
    CREATED = auto()  # Configuring, hooks registered
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
           icon). Must be set before :meth:`run`; ignored on other
           platforms.
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
        self._proxy = None  # TaoEventLoopProxy

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

        # Hooks
        self._hooks: dict[type[AppBaseEvent], list[_Handler]] = {}

        # Windows
        self._windows: dict[int, Window] = {}

        # Menus: roots registered on the main thread (kept alive here so
        # unsendable native objects only drop on the main thread) and the
        # id → item table used to resolve activation events.
        self._menus: list[Any] = []
        self._menu_items: dict[str, Any] = {}

        # Tray icons: id → TrayIcon (main-thread owned; multiple allowed).
        self._trays: dict[str, Any] = {}

        # Completion signal for the Close event dispatch (set by
        # _handle_exit_event, awaited in run()'s finally block).
        self._close_done: Task[None] | None = None

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

    # Hooks

    def on(self, event: type[AppBaseEvent]):
        """Register a handler for an app event class.

        ``app.on(AppEvent.ReadyEvent)(handler)`` — the handler receives
        the event object. Can be sync or async — auto-detected. Runs on
        the asyncio loop (NOT the GUI thread).

        Parameters:
            event: The :class:`AppBaseEvent` subclass to handle.
        """

        def decorator(fn: F) -> F:
            self._hooks.setdefault(event, []).append(fn)
            return fn

        return decorator

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
        if self._state in (AppState.STOPPING, AppState.STOPPED):
            return Task._failed(AppClosedError(self._name))
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
        self._pending[req_id] = handle
        # Race: the main thread may have finished shutdown between our
        # state check and this write — fail the handle ourselves.
        if self._state in (AppState.STOPPING, AppState.STOPPED):
            self._pending.pop(req_id, None)
            if not handle.done():
                handle.set_exception(AppClosedError(self._name))
            return
        log.debug("queued main-thread call (id=%s)", req_id)
        self._cmd_queue.put((req_id, fn, args, kwargs))
        with self._wake_cond:
            self._wake_cond.notify_all()
        if self._proxy is not None:
            self._proxy.send_event(json.dumps({"cmd": "wake", "id": req_id}))

    # Main-thread command processing

    def _drain_commands(self) -> None:
        while not self._cmd_queue.empty():
            req_id, fn, args, kwargs = self._cmd_queue.get_nowait()
            log.debug("executing main-thread call (id=%s)", req_id)
            try:
                result = fn(*args, **kwargs)
                self._respond(req_id, result, None)
            except Exception as exc:
                self._respond(req_id, None, exc)

    def _respond(self, req_id: str, value: object, exc: BaseException | None) -> None:
        handle = self._pending.pop(req_id, None)
        if handle is None or handle.cancelled():
            return
        if exc is not None:
            handle.set_exception(exc)
        else:
            handle.set_result(value)

    # Task scheduling

    def _schedule_task(
        self,
        fn: Callable,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> Task[Any]:
        """Schedule a user function — async on asyncio loop, sync on pool."""
        if inspect.iscoroutinefunction(fn):
            return self._submit_async(fn, args, kwargs)
        else:
            return self._submit_sync(fn, args, kwargs)

    def _submit_async(
        self,
        fn: Callable,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> Task[Any]:
        handle: Task[Any] = Task()
        log.debug("scheduling async task: %s", fn)
        loop = self._async_loop
        if loop is None:
            # App never ran — nothing to schedule on.
            handle.set_exception(RuntimeError("App not running"))
            return handle
        if self._state in (AppState.STOPPING, AppState.STOPPED):
            # Shutdown in progress — scheduling now would race the
            # all_tasks() snapshot in run()'s finally block.
            handle.set_exception(AppClosedError(self._name))
            return handle

        async def _run() -> None:
            try:
                result = await fn(*args, **kwargs)
                if not handle.cancelled():
                    handle.set_result(result)
            except asyncio.CancelledError as exc:
                # CancelledError is a BaseException — the generic handler
                # below cannot catch it. Propagate it to the handle so
                # await/.result() fail fast instead of hanging forever
                # (e.g. tasks cancelled during app shutdown).
                if not handle.cancelled():
                    handle.set_exception(exc)
                raise
            except Exception as exc:
                if not handle.cancelled():
                    handle.set_exception(exc)

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_run()))
        return handle

    def _submit_sync(
        self,
        fn: Callable,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> Task[Any]:
        handle: Task[Any] = Task()
        pool = self._threadpool
        if pool is None:
            handle.set_exception(RuntimeError("App not running"))
            return handle
        # Symmetric with _submit_async: reject new work once shutdown
        # starts so all pending tasks settle as AppClosedError.
        if self._state in (AppState.STOPPING, AppState.STOPPED):
            handle.set_exception(AppClosedError(self._name))
            return handle
        log.debug("scheduling sync task: %s", fn)
        concurrent_future = pool.submit(lambda: fn(*args, **kwargs))
        return Task._from_future(concurrent_future)

    # Event dispatch (internal)

    def _dispatch_handlers(
        self, handlers: list[_Handler], event: AppBaseEvent
    ) -> "Task[None] | None":
        """Run *handlers* for *event* on the asyncio loop.

        Returns a completion signal (a :class:`Task` resolved when all
        handlers finish) or None when there is no loop or no handlers.
        Shared by :meth:`_emit` and the per-item menu activation
        callbacks.
        """
        loop = self._async_loop
        if loop is None or not handlers:
            return None

        log.debug(
            "dispatching %s to %d handler(s)", type(event).__name__, len(handlers)
        )
        done: Task[None] = Task()

        async def _dispatch() -> None:
            try:
                for fn in handlers:
                    try:
                        await run_async(fn, event)
                    except Exception:
                        log.exception(f"Error in {type(event).__name__} handler: {fn}")
            finally:
                done.set_result(None)

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_dispatch()))
        return done

    def _emit(self, event: AppBaseEvent) -> "Task[None] | None":
        """Dispatch an app event to registered handlers on the asyncio loop.

        Returns a completion signal (a :class:`Task` resolved when all
        handlers finish) or None when there is no loop or no handlers.
        Callers
        that don't need to wait may ignore the return value — only
        ``_handle_exit_event`` consumes it.
        """
        return self._dispatch_handlers(self._hooks.get(type(event), []), event)

    # Menu / tray events (GUI thread → asyncio loop)

    def _on_menu_event(self, event: Any) -> None:
        """Called on the GUI thread for every menu activation (the single
        muda global handler). Per-item callbacks run first, then the
        global event is emitted."""
        item = self._menu_items.get(event.id)
        ev = AppEvent.MenuItemActivatedEvent(id=event.id, menu_item=item)
        if item is not None:
            # Resolve the item's own on_activate callbacks on the asyncio
            # loop, in registration order.
            self._dispatch_handlers(item._activate_callbacks, ev)
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
        entry: (
            Callable[[], Coroutine[Any, Any, Any]] | Callable | None
        ) = None,
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
        log.info("App %r starting", self._name)

        self._event_loop = TaoEventLoop(app_id=self._app_id)
        self._proxy = self._event_loop.create_proxy()
        self._main_tid = threading.get_ident()

        global _GUI_THREAD_ID
        _GUI_THREAD_ID = self._main_tid

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
            if sys.platform != "darwin":
                raise ValueError("activation_policy is macOS only")
            self._event_loop.set_activation_policy(self._activation_policy)

        init_menu_events(_menu_event_bridge)
        init_tray_events(_tray_event_bridge)

        if sys.platform == "darwin":
            try:
                from lumiview.menu import Menu, Submenu

                _default = Menu.default_app_menu()
                _default._materialize().init_for_nsapp()
                for _item in _default._items:
                    if (
                        isinstance(_item, Submenu)
                        and _item._is_window_menu
                        and _item._inner is not None
                    ):
                        _item._inner.set_as_windows_menu_for_nsapp()
            except Exception:
                log.exception("Failed to install default macOS menu")

        # Install Ctrl+C handler. signal.signal() only works on the
        # main thread — background-thread runs (e.g. future test
        # harness) skip it.
        def _sigint_handler(signum, frame):
            log.info("Ctrl+C received, shutting down...")
            self.exit()

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
            log.info("App %r running", self._name)

            # Run the Tao event loop (blocks main thread).
            self._event_loop.run(self._on_tao_event)
        except Exception:
            log.exception("Event loop crashed")
        finally:
            self._state = AppState.STOPPED
            log.info("App %r stopped", self._name)

            signal.signal(signal.SIGINT, original_sigint)

            # Wait for Close handlers to finish before stopping the
            # asyncio loop, so cleanup code actually runs.
            if self._close_done is not None:
                try:
                    self._close_done.result()
                except KeyboardInterrupt:
                    log.warning("interrupted while waiting for Close handlers")
                except BaseException:
                    log.exception("Close handler wait failed")

            # Each cleanup step below is individually guarded: a second
            # Ctrl+C (KeyboardInterrupt — the original handler is already
            # restored) must not skip the remaining steps, so run() still
            # returns cleanly and no handle is left hanging.
            # 1. Cancel pending asyncio tasks so hung awaits fail fast
            #    with CancelledError (Task.cancel() is thread-safe), then
            #    stop the loop. Tasks created after the all_tasks()
            #    snapshot — only possible from Close handlers that
            #    overran the timeout — are not cancelled; they are
            #    abandoned with the daemon async thread below.
            try:
                if self._async_loop is not None:
                    for t in asyncio.all_tasks(self._async_loop):
                        t.cancel()
                    self._async_loop.call_soon_threadsafe(self._async_loop.stop)
                if self._async_thread is not None:
                    self._async_thread.join(timeout=_SHUTDOWN_TIMEOUT)
                    if self._async_thread.is_alive():
                        log.warning(
                            f"async thread did not exit within remaining budget ({_SHUTDOWN_TIMEOUT}s)"
                        )
            except BaseException:
                log.exception("Interrupted during asyncio shutdown")

            # 2. Fail pending main-thread command handles. After the
            #    event loop returns, the main thread no longer drains
            #    the command queue — these would otherwise hang forever.
            try:
                for handle in list(self._pending.values()):
                    if not handle.done():
                        handle.set_exception(AppClosedError(self._name))
                self._pending.clear()
            except BaseException:
                log.exception("Interrupted while failing pending handles")

            # 3. Thread pool: cancel queued (not yet started) work.
            #    Tasks already running on pool threads cannot be
            #    interrupted — documented limitation.
            if self._threadpool is not None:
                try:
                    self._threadpool.shutdown(wait=False, cancel_futures=True)
                except BaseException:
                    log.exception("Interrupted while shutting down thread pool")

            _GUI_THREAD_ID = None
            set_loop_running(False)

        return self._exit_code if self._exit_code is not None else 0

    def exit(self, code: int = 0) -> None:
        """Request a graceful shutdown; ``run()`` returns *code*.

        Only records the request (first request wins) and wakes the
        main thread — it does **not** transition the state. The actual
        cleanup (closing windows, emitting :class:`AppCloseEvent`) runs
        when the exit event is handled on the main thread, so
        ``_handle_exit_event`` remains the single transition into
        STOPPING.
        """
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
        if self._proxy is not None:
            try:
                self._proxy.send_event(json.dumps({"cmd": "exit"}))
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
            for win in list(self._windows.values()):
                win._sync_webview_visibility()
        else:
            for win in list(self._windows.values()):
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
            for win in list(self._windows.values()):
                win._sync_webview_visibility()
        else:
            for win in list(self._windows.values()):
                win.show()

    @main_thread
    def set_dock_visibility(self, visible: bool) -> None:
        """Show (``True``) or hide (``False``) the macOS Dock icon.

        Combined with ``App(activation_policy=ActivationPolicy.Accessory)``
        this makes a menu-bar/tray application. **macOS only** — raises
        :class:`AttributeError` elsewhere.
        """
        if self._event_loop is None:
            return
        self._event_loop.set_dock_visibility(visible)

    def _run_asyncio(self, entry: Callable | None) -> None:
        try:
            self._async_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._async_loop)

            async def _main() -> None:
                self._emit(AppEvent.ReadyEvent())

                if entry is not None:
                    try:
                        await run_async(entry)
                    except Exception:
                        log.exception("Error in entry point")

            self._async_loop.create_task(_main())
        except BaseException:
            log.exception("Failed to start the asyncio loop")
            self._async_ready.set()
            return

        self._async_ready.set()
        try:
            self._async_loop.run_forever()
        except BaseException:
            log.exception("Asyncio loop crashed")

    # Window tracking

    def _remove_window(self, win_id: int) -> None:
        """Called when a Window is closed — clean up tracking."""
        log.info("Window closed (id=%s)", win_id)
        self._windows.pop(win_id, None)
        if self._exit_on_last_window and not self._windows:
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
            win = self._windows.get(wid)
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

        for win in list(self._windows.values()):
            try:
                if win._webview is not None:
                    win._webview.close()
                win._window = None
                win._webview = None
            except Exception:
                log.exception("Error closing window")

        self._windows.clear()

        # Menus and trays: clear native handles here, on the main thread
        # (unsendable objects may only drop on this thread). Trays first —
        # a tray may hold Arc references into a menu tree; detaching the
        # subclassed window before the menu drops is the safe order on
        # Windows.
        for tray in list(self._trays.values()):
            try:
                tray._tray = None
            except Exception:
                log.exception("Error closing tray icon")
        self._trays.clear()

        for menu in self._menus:
            try:
                menu._inner = None
            except Exception:
                log.exception("Error releasing menu")
        for item in self._menu_items.values():
            try:
                item._inner = None
            except Exception:
                log.exception("Error releasing menu item")
        self._menus.clear()
        self._menu_items.clear()

        # Emit Close for remaining handlers. The completion signal is
        # awaited in run()'s finally block before the asyncio loop stops,
        # so cleanup handlers actually run.
        self._close_done = self._emit(AppEvent.AppCloseEvent())

        return EventLoopControl.Exit


# Error types


class AppClosedError(RuntimeError):
    """Raised when an operation is attempted after the app has closed."""

    def __init__(self, app_name: str = "lumiview") -> None:
        super().__init__(f"{app_name} has been closed")


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
        log.exception("menu event dispatch failed")


def _tray_event_bridge(event: Any) -> None:
    """Forward a native tray event to the current App (GUI thread)."""
    try:
        App.get()._on_tray_event(event)
    except Exception:
        log.exception("tray event dispatch failed")
