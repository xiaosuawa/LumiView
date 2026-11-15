"""task(): sync/async paths, contextvars, admission and BaseException settling.

Covers the two scheduling paths deliberately:

* sync functions run on the App's thread pool (old path) and must see the
  caller's contextvars;
* async functions run on the asyncio loop;
* a BaseException from a sync function must settle the Task;
* after ``exit()`` both paths fail fast with ``AppClosedError``;
* before ``run()`` both paths fail with ``RuntimeError`` instead of hanging.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys

from lumiview import App, AppClosedError, task

_marker: contextvars.ContextVar[str] = contextvars.ContextVar(
    "marker", default="unset"
)


def _read_marker() -> str:
    return _marker.get()


async def _double(value: int) -> int:
    await asyncio.sleep(0)
    return value * 2


async def _read_marker_async() -> str:
    await asyncio.sleep(0)
    return _marker.get()


def _raise_keyboard_interrupt() -> None:
    raise KeyboardInterrupt


def _call_from_worker() -> str:
    _marker.set("worker")
    return task(_read_marker).result(timeout=5)


async def _entry() -> None:
    app = App.get()

    # Sync path: the pool thread must see the caller's contextvars.
    assert await asyncio.to_thread(_call_from_worker) == "worker"

    # Async path: the new task must inherit the caller's contextvars too.
    _marker.set("entry")
    assert await task(_read_marker_async) == "entry"
    assert await task(_double, 21) == 42

    # A BaseException from a sync function must settle the Task instead of
    # leaving it pending forever.
    handle = task(_raise_keyboard_interrupt)
    try:
        await handle
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt did not reach the caller")

    # After exit(), neither path may admit new work. Both Tasks are already
    # settled, so ``exception()`` is a plain read (no asyncio-thread block).
    app.exit(0)

    for handle in (task(lambda: None), task(_double, 1)):
        exc = handle.exception()
        assert isinstance(exc, AppClosedError), (
            f"task() admitted work after exit(): {exc!r}"
        )


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)

    # Before run(): the App exists but has no loop/pool, so task() must
    # return a failed Task instead of raising or hanging.
    for handle in (task(lambda: None), task(_double, 1)):
        try:
            handle.result(timeout=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("task() did not fail before App.run()")

    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
