from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
from typing import (
    Any,
    Callable,
    Generator,
    Generic,
    ParamSpec,
    TypeVar,
)

P = ParamSpec("P")
T = TypeVar("T")

# Deadlock detection
class TaskDeadlockError(RuntimeError):
    """Raised when blocking the GUI thread on an incomplete Task."""

    def __init__(self) -> None:
        super().__init__(
            "Cannot block the GUI thread with .result(). "
            "Use await from async code, or .on_done() / .add_done_callback() "
            "for callback-style handling."
        )


def _check_deadlock() -> None:
    """Raise TaskDeadlockError if called from the GUI thread."""
    # Deferred import: _app sets this global in App.run(); importing by value
    # at module load would freeze it at None (see App.run / _GUI_THREAD_ID).
    from lumiview.app import _GUI_THREAD_ID

    if _GUI_THREAD_ID is not None and threading.get_ident() == _GUI_THREAD_ID:
        raise TaskDeadlockError()


def _log_unhandled_task_error(task: "Task[Any]") -> None:
    """Log a failed-but-never-retrieved Task with its traceback.

    Called from ``Task.__del__`` — must never raise: the interpreter may
    already be tearing down, and an exception in ``__del__`` would only
    get printed, not propagated.
    """
    try:
        exc = task.exception()
        if not isinstance(exc, BaseException):
            return
        logging.getLogger("lumiview.task").error(
            "Task failed and its exception was never retrieved — use "
            "await / .result() / .on_done() to handle failures: %s",
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    except Exception:
        pass


# Task[T] — a Future with __await__ and deadlock detection

class Task(concurrent.futures.Future, Generic[T]):
    """A handle to a running (or completed) operation.

    Three ways to use::

        await task                    # async  — any event loop
        task.result()                 # sync   — any thread except GUI
        task.on_done(lambda val: ...) # callback — any thread (alias for add_done_callback)
    """

    def __init__(self) -> None:
        super().__init__()
        # Self-managed "exception was consumed" flag. Python 3.12 removed
        # the CPython _exception_was_retrieved machinery (and the
        # "Future exception was never retrieved" warning) entirely, so
        # __del__ tracks consumption through the consumption APIs below.
        self._lumi_retrieved = False

    def result(self, timeout: float | None = None) -> T:
        """Block until done and return the value.

        Raises:
            TaskDeadlockError: If called from the GUI thread on an
                **incomplete** task (completed tasks return instantly).
            TimeoutError: If *timeout* is exceeded.
            BaseException: The original exception if the task failed.
        """
        if not self.done():
            _check_deadlock()
        try:
            return super().result(timeout)
        except BaseException:
            self._lumi_retrieved = True
            raise

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """Block until done and return the exception (or None)."""
        if not self.done():
            _check_deadlock()
        try:
            return super().exception(timeout)
        finally:
            # Inspecting the exception counts as consuming it (the base
            # class's retrieved flag is gone in Python 3.12).
            self._lumi_retrieved = True

    def __await__(self) -> Generator[Any, None, T]:
        """``await task`` — fresh ``wrap_future`` each time, no loop binding."""
        return asyncio.wrap_future(self).__await__()

    def on_done(self, callback: Callable[[T], Any]) -> None:
        """Register a callback — a convenience wrapper around
        :meth:`~concurrent.futures.Future.add_done_callback`.

        The callback receives the result value (not the Future).
        Exceptions are NOT passed to the callback; use
        :meth:`add_done_callback` directly if you need to handle errors.
        """

        def _wrapper(fut: concurrent.futures.Future) -> None:
            if not fut.cancelled() and fut.exception() is None:
                callback(fut.result())

        self.add_done_callback(_wrapper)

    def __del__(self) -> None:
        """
        Surface unhandled task failures via logging.
        """
        try:
            if (
                self.done()
                and not self.cancelled()
                and self.exception() is not None
                and not getattr(self, "_lumi_retrieved", False)
            ):
                _log_unhandled_task_error(self)
        except Exception:
            pass

    # Internal (called by App scheduler)

    @classmethod
    def _from_future(cls, fut: concurrent.futures.Future) -> Task[T]:
        """Wrap an existing Future as a Task.

        When the underlying future completes, the Task is resolved.
        """
        task = cls()

        def _propagate(f: concurrent.futures.Future) -> None:
            if f.cancelled():
                task.cancel()
            elif (exc := f.exception()) is not None:
                task.set_exception(exc)
            else:
                task.set_result(f.result())

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


# Public: lightweight async/sync dispatch (no Task overhead)

async def run_async(
    fn: Callable[..., Any],
    *args: Any,
    pool: concurrent.futures.ThreadPoolExecutor | None = None,
    **kwargs: Any,
) -> Any:
    """Execute *fn* on the asyncio loop — no Task created.

    - async functions: awaited directly (zero overhead).
    - sync functions: dispatched to *pool* via ``loop.run_in_executor``.

    Use inside async contexts when you need to run a mixed sync/async
    callback without the full :func:`task` machinery::

        from lumiview.task import run_async
        await run_async(my_callback, key="x")
    """
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    loop = asyncio.get_running_loop()
    if pool is None:
        raise RuntimeError("Thread pool required for sync function dispatch")
    return await loop.run_in_executor(pool, lambda: fn(*args, **kwargs))


# Public factory: task()

def task(
    fn: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Task[T]:
    """Run ``fn(*args, **kwargs)`` concurrently and return a :class:`Task`.

    - **async** functions → scheduled on the asyncio loop.
    - **sync** functions → dispatched to the App's thread pool.

    Returns a :class:`Task` that can be ``await``-ed, ``.result()``-blocked,
    or given a callback via ``.on_done()``.

    Raises:
        RuntimeError: If no :class:`App` instance has been created yet.
    """
    from lumiview.app import App  # deferred import to avoid circular dep

    return App.get()._schedule_task(fn, args, kwargs)
