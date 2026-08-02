from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
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

_UNSET: Any = object()

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
    from lumiview._app import _GUI_THREAD_ID

    if _GUI_THREAD_ID is not None and threading.get_ident() == _GUI_THREAD_ID:
        raise TaskDeadlockError()


# Task[T] — a Future with __await__ and deadlock detection

class Task(concurrent.futures.Future, Generic[T]):
    """A handle to a running (or completed) operation.

    Three ways to use::

        await task                    # async  — any event loop
        task.result()                 # sync   — any thread except GUI
        task.on_done(lambda val: …)   # callback — any thread (alias for add_done_callback)
    """

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
        return super().result(timeout)

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """Block until done and return the exception (or None)."""
        if not self.done():
            _check_deadlock()
        return super().exception(timeout)

    def __await__(self) -> Generator[Any, None, T]:
        """``await task`` — fresh ``wrap_future`` each time, no loop binding."""
        return asyncio.wrap_future(self).__await__()

    def on_done(self, callback: Callable[[T], Any]) -> None:
        """Register a callback — a convenience wrapper around ``add_done_callback``.

        The callback receives the result value (not the Future).
        Exceptions are NOT passed to the callback; use ``add_done_callback``
        directly if you need to handle errors.
        """

        def _wrapper(fut: concurrent.futures.Future) -> None:
            if not fut.cancelled() and fut.exception() is None:
                callback(fut.result())

        self.add_done_callback(_wrapper)

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


# Internal: lightweight async/sync dispatch (zero Task overhead)

async def _run_async(
    fn: Callable[..., Any],
    *args: Any,
    pool: concurrent.futures.ThreadPoolExecutor | None = None,
    **kwargs: Any,
) -> Any:
    """Execute *fn* on the asyncio loop — no Task created.

    - async functions: awaited directly (zero overhead).
    - sync functions: dispatched to *pool* via ``loop.run_in_executor``.
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
    from lumiview._app import App  # deferred import to avoid circular dep

    return App.get()._schedule_task(fn, args, kwargs)
