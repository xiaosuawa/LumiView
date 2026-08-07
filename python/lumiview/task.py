from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
import time
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


# Asyncio deadlock detection
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


# Task[T] — a Future with __await__ and thread-aware blocking


class Task(concurrent.futures.Future, Generic[T]):
    """A handle to a running (or completed) operation.

    Three ways to use::

        await task                    # async  — any event loop
        task.result()                 # sync   — any thread (GUI drains commands)
        task.on_done(lambda val: ...) # callback — any thread (alias for add_done_callback)
    """

    def __init__(self) -> None:
        super().__init__()
        self._lumi_retrieved = False

    def result(self, timeout: float | None = None) -> T:
        """Block until done and return the value.

        Raises:
            TaskDeadlockError: If called from the asyncio thread on an
                **incomplete** task (completed tasks return instantly) —
                the loop would stall. On the GUI thread an incomplete
                task is waited on while the main-thread command queue
                keeps running (the window freezes meanwhile).
            TimeoutError: If *timeout* is exceeded.
            BaseException: The original exception if the task failed.
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
            # Inspecting the exception counts as consuming it (the base
            # class's retrieved flag is gone in Python 3.12).
            self._lumi_retrieved = True

    def _block(self, timeout: float | None) -> None:
        """Block until done, adapting to the calling thread.

        Only called when the task is incomplete.

        - **GUI thread**: drains the main-thread command queue while
          waiting — a queued command may be the very operation this task
          waits on (e.g. a ``call_on_main`` from the asyncio thread), so
          the wait can always make progress (logged at debug level, since
          the window freezes meanwhile).
        - **thread with a running event loop**: the loop would stall, so
          raise :class:`TaskDeadlockError` — ``await`` is the correct
          form there (``Task`` awaits from any loop).
        - **other threads**: block normally (like ``Future.result``).
        """
        from lumiview.app import _GUI_THREAD_ID

        if _GUI_THREAD_ID is not None and threading.get_ident() == _GUI_THREAD_ID:
            self._block_on_gui(timeout)
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        else:
            raise TaskDeadlockError()

    def _block_on_gui(self, timeout: float | None) -> None:
        """Wait on the GUI thread, running queued main-thread commands.

        Extracted from ``Window._dispatch_preventable``'s wait pattern:
        commands enqueued by the task we wait on keep executing, so the
        wait always makes progress instead of deadlocking.
        """

        logging.getLogger("lumiview.task").debug(
            "Blocking the GUI thread on Task.result() — the window may freeze."
        )

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
    fn: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
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
    from lumiview.app import App
    return await loop.run_in_executor(App.get()._threadpool, lambda: fn(*args, **kwargs))


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
    from lumiview.app import App

    return App.get()._schedule_task(fn, args, kwargs)
