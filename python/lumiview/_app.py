from __future__ import annotations

import asyncio
import inspect
import json
import logging
import queue
import signal
import threading
import uuid
from collections.abc import Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum, auto
from typing import Any, Callable, TypeVar, ParamSpec, TYPE_CHECKING

from lumiview._core import TaoEventLoop, TaoEvent, EventLoopControl, UserEvent

from lumiview._events import AppHookEvent
from lumiview._task import Task, _run_async

P = ParamSpec("P")
T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])

_Handler = Callable[..., Any]
_Command = tuple[str, Callable[..., Any], tuple, dict[str, Any]]

log = logging.getLogger("lumiview.app")

# tao/GUI thread identity for Task deadlock detection. Assigned by
# App.run() and reset on exit. Lives in this module because _task's
# _check_deadlock() reads it via deferred import — a by-value import
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

    Create one instance, configure it, then call ``app.run(entry)``.

    Parameters:
        name: Application name (used for platform-specific identity).
        exit_on_last_window: If True (default), exit when the last window closes.
           Set to False for tray-based apps.
        max_workers: Thread pool size for sync ``task()`` calls.

    Lifecycle: register an entry via ``run(entry)`` (main flow) and/or
    observe via ``app.on(AppHookEvent.Ready)``. Request exit with
    ``app.exit(code)``; cleanup code goes in ``app.on(AppHookEvent.Close)``
    handlers (awaited during shutdown).
    """

    _instance: App | None = None

    def __init__(
        self,
        *,
        name: str = "lumiview",
        exit_on_last_window: bool = True,
        max_workers: int | None = 6,
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

        # State
        self._state = AppState.CREATED
        self._exit_code: int = 0

        # Rust bindings (created in run())
        self._event_loop: TaoEventLoop | None = None
        self._proxy = None  # TaoEventLoopProxy

        # Thread identity
        self._main_tid: int | None = None

        # Command queue (any thread → main thread)
        self._cmd_queue: queue.Queue[_Command] = queue.Queue()
        self._pending: dict[str, Task[Any]] = {}

        # Async infrastructure
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._threadpool: ThreadPoolExecutor | None = None

        # Hooks
        self._hooks: dict[AppHookEvent, list[_Handler]] = {
            evt: [] for evt in AppHookEvent
        }

        # Windows
        self._windows: dict[int, Window] = {}

        # Completion signal for the Close event dispatch (set by
        # _handle_exit_event, awaited in run()'s finally block).
        self._close_done: Future[None] | None = None

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
        return self._name

    @property
    def state(self) -> AppState:
        return self._state

    # Hooks

    def on(self, event: AppHookEvent):
        """Register a handler for an app-level event.

        Handler can be sync or async — auto-detected.
        Runs on the asyncio loop (NOT the GUI thread).
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
        req_id = str(uuid.uuid4())
        self._pending[req_id] = handle
        # Race: the main thread may have finished shutdown between our
        # state check and this write — fail the handle ourselves.
        if self._state in (AppState.STOPPING, AppState.STOPPED):
            self._pending.pop(req_id, None)
            if not handle.done():
                handle.set_exception(AppClosedError(self._name))
            return
        self._cmd_queue.put((req_id, fn, args, kwargs))
        if self._proxy is not None:
            self._proxy.send_event(json.dumps({"cmd": "wake", "id": req_id}))

    # Main-thread command processing

    def _drain_commands(self) -> None:
        while not self._cmd_queue.empty():
            req_id, fn, args, kwargs = self._cmd_queue.get_nowait()
            try:
                result = fn(*args, **kwargs)
                self._respond(req_id, result, None)
            except Exception as exc:
                self._respond(req_id, None, exc)

    def _respond(self, req_id: str, value: object, exc: BaseException | None) -> None:
        handle = self._pending.pop(req_id, None)
        if handle is None:
            return
        if exc is not None:
            handle.set_exception(exc)
        else:
            handle.set_result(value)

    # Task scheduling

    def _schedule_task(
        self,
        fn: Callable[..., Any],
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
        fn: Callable[..., Any],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> Task[Any]:
        handle: Task[Any] = Task()
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
                handle.set_result(result)
            except asyncio.CancelledError as exc:
                # CancelledError is a BaseException — the generic handler
                # below cannot catch it. Propagate it to the handle so
                # await/.result() fail fast instead of hanging forever
                # (e.g. tasks cancelled during app shutdown).
                handle.set_exception(exc)
                raise
            except Exception as exc:
                handle.set_exception(exc)

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_run()))
        return handle

    def _submit_sync(
        self,
        fn: Callable[..., Any],
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
        concurrent_future = pool.submit(lambda: fn(*args, **kwargs))
        return Task._from_future(concurrent_future)

    # Event dispatch (internal)

    def _emit(self, event: AppHookEvent, *args: object) -> "Future[None] | None":
        """Dispatch an app event to registered handlers on the asyncio loop.

        Returns a completion signal (a plain ``concurrent.futures.Future``
        resolved when all handlers finish) or None when there is no loop
        or no handlers. Callers that don't need to wait may ignore the
        return value — only ``_handle_exit_event`` consumes it.
        """
        loop = self._async_loop
        if loop is None:
            return

        handlers = self._hooks.get(event, [])
        if not handlers:
            return

        done: Future[None] = Future()

        async def _dispatch() -> None:
            try:
                for fn in handlers:
                    try:
                        await _run_async(fn, *args, pool=self._threadpool)
                    except Exception:
                        log.exception(f"Error in {event.name} handler: {fn}")
            finally:
                done.set_result(None)

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_dispatch()))
        return done

    # Run loop

    def run(
        self,
        entry: (
            Callable[[], Coroutine[Any, Any, Any]] | Callable[..., Any] | None
        ) = None,
    ) -> int:
        """Start the application. Blocks until exit.

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

        self._event_loop = TaoEventLoop()
        self._proxy = self._event_loop.create_proxy()
        self._main_tid = threading.get_ident()

        global _GUI_THREAD_ID
        _GUI_THREAD_ID = self._main_tid

        self._threadpool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="lumiview-pool",
        )

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

        # Wait for asyncio loop to be ready.
        while self._async_loop is None:
            pass  # busy-wait — very brief

        self._state = AppState.RUNNING

        # Run the Tao event loop (blocks main thread).
        try:
            self._event_loop.run(self._on_tao_event)
        except Exception:
            log.exception("Event loop crashed")
        finally:
            self._state = AppState.STOPPED

            signal.signal(signal.SIGINT, original_sigint)

            # Wait for Close handlers to finish before stopping the
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

        return self._exit_code

    def exit(self, code: int = 0) -> None:
        """Request a graceful shutdown; ``run()`` returns *code*.

        Once shutdown has started (STOPPING/STOPPED), later calls are
        ignored so the first requested exit code wins.
        """
        if self._state in (AppState.STOPPING, AppState.STOPPED):
            # Shutdown already in progress — ignore the request. Keeps
            # _exit_code monotonic: a window closing during STOPPING
            # (_remove_window, code 0) can no longer overwrite an
            # explicit exit(code).
            return
        self._exit_code = code
        self._state = AppState.STOPPING
        if self._proxy is not None:
            try:
                self._proxy.send_event(json.dumps({"cmd": "exit"}))
            except Exception:
                pass

    def _run_asyncio(self, entry: Callable[..., Any] | None) -> None:
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)

        async def _main() -> None:
            self._emit(AppHookEvent.Ready)

            if entry is not None:
                try:
                    await _run_async(entry, pool=self._threadpool)
                except Exception:
                    log.exception("Error in entry point")

        self._async_loop.create_task(_main())
        self._async_loop.run_forever()

    # Window tracking

    def _remove_window(self, win_id: int) -> None:
        """Called when a Window is closed — clean up tracking."""
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

        # Every other tao event is window-scoped — route it to the window.
        if (wid := event.window_id) is not None:
            win = self._windows.get(wid)
            if win is not None:
                win._on_tao_event(event)

        return EventLoopControl.Continue

    def _handle_exit_event(self) -> EventLoopControl:
        """Graceful shutdown sequence."""
        self._state = AppState.STOPPING

        for win in list(self._windows.values()):
            try:
                if win._webview is not None:
                    win._webview.close()
                win._tao = None
                win._webview = None
            except Exception:
                log.exception("Error closing window")

        self._windows.clear()

        # Emit Close for remaining handlers. The completion signal is
        # awaited in run()'s finally block before the asyncio loop stops,
        # so cleanup handlers actually run.
        self._close_done = self._emit(AppHookEvent.Close)

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
