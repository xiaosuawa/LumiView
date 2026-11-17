from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import inspect
import logging
import time
from typing import (
    Any,
    Awaitable,
    Callable,
    Generator,
    Generic,
    ParamSpec,
    overload,
)

from typing_extensions import TypeVar

P = ParamSpec("P")
T = TypeVar("T", default=Any)

_log = logging.getLogger("lumiview.task")


class TaskDeadlockError(RuntimeError):
    """Raised when blocking a thread with a running event loop on an
    incomplete Task."""

    def __init__(self) -> None:
        super().__init__(
            "Cannot block the asyncio thread with .result() — the event "
            "loop would stall and every coroutine on it freezes. "
            "Use `await task` instead."
        )


def _log_unhandled_task_error(task: "Task[Any]") -> None:
    """Log a failed-but-never-retrieved Task (called from ``__del__``)."""
    try:
        exc = task.exception()
        if not isinstance(exc, BaseException):
            return
        _log.error(
            "Task failed and its exception was never retrieved — use "
            "await / .result() / .on_done() to handle failures: %s",
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    except Exception:
        pass


class Task(concurrent.futures.Future, Generic[T]):
    """A handle to a running (or completed) operation.

    ``await task``, ``task.result()`` or ``task.on_done(cb)``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lumi_retrieved = False

    def result(self, timeout: float | None = None) -> T:
        """Block until done and return the value.

        Raises ``TaskDeadlockError`` from the asyncio thread (use ``await``),
        ``TimeoutError``, or the original exception.
        """
        if not self.done():
            self._block(timeout)
        try:
            return super().result(timeout)
        except BaseException:
            self._lumi_retrieved = True
            raise

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """Block until done and return the exception (or None)."""
        if not self.done():
            self._block(timeout)
        try:
            return super().exception(timeout)
        finally:
            # Reading it counts as consuming it (3.12 dropped the base flag).
            self._lumi_retrieved = True

    def with_timeout(
        self,
        timeout: float,
        *,
        message: str | None = None,
    ) -> "Task[T]":
        """Return a new Task that mirrors this one, or fails with ``TimeoutError``.

        Unlike :meth:`result`, this never blocks the caller: the returned Task can be
        awaited or handled with ``on_done()`` from any thread. The source Task keeps
        running when the timeout expires, so other waiters still see its result.
        """
        from lumiview.app import App

        app = App._instance
        if app is None or app._async_loop is None:
            return Task._failed(RuntimeError("App is not running"))

        outer: Task[T] = Task()

        def _mirror() -> None:
            if self.cancelled():
                outer._settle(exc=asyncio.CancelledError())
                return
            exc = self.exception()
            if exc is not None:
                outer._settle(exc=exc)
            else:
                outer._settle(result=self.result())

        async def _wait() -> None:
            inner = asyncio.ensure_future(asyncio.shield(asyncio.wrap_future(self)))
            try:
                done, _ = await asyncio.wait({inner}, timeout=timeout)
                if not done:
                    # The source may have settled just before the timer fired.
                    if self.done():
                        _mirror()
                        return
                    inner.cancel()
                    await asyncio.gather(inner, return_exceptions=True)
                    outer._settle(
                        exc=TimeoutError(
                            message or f"Task timed out after {timeout}s"
                        ),
                    )
                    return
                try:
                    result = inner.result()
                except BaseException as exc:
                    outer._settle(exc=exc)
                else:
                    outer._settle(result=result)
            except asyncio.CancelledError as exc:
                # The app closed while the timeout was pending. If the source
                # already settled (e.g. the ClosedEvent it was waiting for was
                # dispatched first), mirror that instead of the cancellation.
                if self.done():
                    _mirror()
                else:
                    outer._settle(exc=exc)
            except BaseException as exc:
                if self.done():
                    _mirror()
                else:
                    outer._settle(exc=exc)
            finally:
                if not inner.done():
                    inner.cancel()

        if not app._spawn(_wait()):
            outer._settle(exc=RuntimeError("App is not running"))
        return outer

    def _block(self, timeout: float | None) -> None:
        """Block until done, adapting to the calling thread.

        GUI thread: drains commands (the window freezes). A thread with a running loop:
        ``TaskDeadlockError``. Otherwise: plain block.
        """
        from lumiview.app import App

        app = App._instance

        if app is not None and app.is_main_thread():
            self._block_on_gui(timeout)
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        else:
            raise TaskDeadlockError()

    def _block_on_gui(self, timeout: float | None) -> None:
        """Wait on the GUI thread, draining queued commands meanwhile."""

        _log.debug("Blocking the GUI thread on Task.result() — the window may freeze.")

        from lumiview.app import App

        app = App.get()
        cond = app._wake_cond

        def _notify(_: Any) -> None:
            with cond:
                cond.notify_all()

        self.add_done_callback(_notify)
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.done():
            app._drain_commands()
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError
            with cond:
                cond.wait_for(
                    lambda: self.done() or not app._cmd_queue.empty(),
                    timeout=remaining,
                )

    def __await__(self) -> Generator[Any, None, T]:
        """``await task`` — fresh ``wrap_future`` each time, no loop binding."""
        return asyncio.wrap_future(self).__await__()

    def on_done(self, callback: Callable[[T], Any]) -> None:
        """Register a callback that receives the result (errors are not passed)."""

        def _wrapper(fut: concurrent.futures.Future) -> None:
            if not fut.cancelled() and fut.exception() is None:
                callback(fut.result())

        self.add_done_callback(_wrapper)

    def on_exception(self, callback: Callable[[BaseException], Any]) -> None:
        """Register a callback that receives the failure."""

        def _wrapper(fut: concurrent.futures.Future) -> None:
            if not fut.cancelled() and (exc := fut.exception()) is not None:
                callback(exc)

        self.add_done_callback(_wrapper)

    def __del__(self) -> None:
        """
        Surface unhandled task failures via logging.
        """
        try:
            # Do not call self.exception() here: it would mark the error retrieved.
            if (
                not self.done()
                or self.cancelled()
                or getattr(self, "_lumi_retrieved", False)
            ):
                return
            exc = super().exception()
            if exc is None or isinstance(exc, asyncio.CancelledError):
                # A cancelled awaitable is not a failure.
                return
            _log_unhandled_task_error(self)
        except Exception:
            pass

    def _settle(
        self,
        result: Any = None,
        *,
        exc: BaseException | None = None,
    ) -> None:
        """Resolve this Task unless it is already settled.

        ``Future`` has no atomic "set if not done", and both ``set_result`` and
        ``set_exception`` raise ``InvalidStateError`` once the Task was cancelled.
        Settling happens from callbacks on different threads, so swallow that race.
        """
        if self.done():
            return
        try:
            if exc is not None:
                self.set_exception(exc)
            else:
                self.set_result(result)
        except concurrent.futures.InvalidStateError:
            pass

    @classmethod
    def _from_future(cls, fut: concurrent.futures.Future) -> Task[T]:
        """Wrap an existing Future as a Task."""
        task = cls()

        def _propagate(f: concurrent.futures.Future) -> None:
            if f.cancelled():
                # ``cancel()`` on an already-settled Task is a no-op.
                task.cancel()
                return
            exc = f.exception()
            if exc is not None:
                task._settle(exc=exc)
            else:
                task._settle(result=f.result())

        fut.add_done_callback(_propagate)
        return task

    @classmethod
    def _done(cls, value: T) -> Task[T]:
        """Return an already-resolved Task."""
        task = cls()
        task.set_result(value)
        return task

    @classmethod
    def _failed(cls, exc: BaseException) -> Task[T]:
        """Return an already-failed Task."""
        task = cls()
        task.set_exception(exc)
        return task


@overload
async def run_async(
    fn: Callable[P, Awaitable[T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T: ...


@overload
async def run_async(
    fn: Callable[P, Awaitable[T] | T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T: ...


@overload
async def run_async(
    fn: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T: ...


async def run_async(
    fn: Callable[P, Awaitable[T] | T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Execute *fn* on the asyncio loop — no Task created.

    Async functions are awaited, sync ones run on the thread pool (carrying the
    caller's contextvars). Deliberately skips the admission check: shutdown handlers
    need it.
    """
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)

    from lumiview.app import App

    app = App.get()
    pool = app._threadpool
    if pool is None:
        raise RuntimeError("App is not running — call App.run() first")

    # Threads do not inherit contextvars; carry them.
    ctx = contextvars.copy_context()
    result = await asyncio.get_running_loop().run_in_executor(
        pool, lambda: ctx.run(fn, *args, **kwargs)
    )
    if inspect.isawaitable(result):
        return await result
    return result


@overload
def task(
    fn: Callable[P, Awaitable[T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Task[T]: ...


@overload
def task(
    fn: Callable[P, Awaitable[T] | T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Task[T]: ...


@overload
def task(
    fn: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Task[T]: ...


def task(
    fn: Callable[P, Awaitable[T] | T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Task[T]:
    """Run ``fn(*args, **kwargs)`` concurrently and return a :class:`Task`.

    Async functions go to the asyncio loop, sync ones to the thread pool. Fails with
    ``RuntimeError`` before ``run()`` and ``AppClosedError`` once the native loop
    returned; work started during the close phase is allowed but cancelled when the
    loop is finalized.
    """
    from lumiview.app import App, AppClosedError, AppState

    app = App.get()

    if _log.isEnabledFor(logging.DEBUG):
        from lumiview._utils import fn_name

        _log.debug("scheduling task: %s", fn_name(fn))

    state = app.state
    if state is AppState.CREATED:
        # App exists but run() has not started the loop/pool yet.
        return Task._failed(
            RuntimeError("App is not running — call App.run() first")
        )
    if not app.is_running:
        return Task._failed(AppClosedError())

    if not inspect.iscoroutinefunction(fn):
        ctx = contextvars.copy_context()

        pool = app._threadpool
        if pool is None:
            return Task._failed(
                RuntimeError("App is not running — call App.run() first")
            )

        try:
            future = pool.submit(ctx.run, fn, *args, **kwargs)
        except RuntimeError:
            # The pool closed between the admission check and submit().
            return Task._failed(AppClosedError())
        return Task._from_future(future)

    if app.async_loop is None:
        return Task._failed(RuntimeError("App is not running — call App.run() first"))

    handle: Task[T] = Task()
    ctx = contextvars.copy_context()

    async def _run() -> None:
        if not app.is_running:
            handle._settle(exc=AppClosedError())
            return
        try:
            result = await fn(*args, **kwargs)
        except asyncio.CancelledError as exc:
            handle._settle(exc=exc)
            raise
        except BaseException as exc:
            handle._settle(exc=exc)
            return
        handle._settle(result=result)

    if not app._spawn(_run(), context=ctx):
        handle._settle(exc=AppClosedError())
    return handle
