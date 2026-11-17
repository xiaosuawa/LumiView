"""task(): sync/async paths, contextvars, admission and BaseException settling.

Covers the two scheduling paths deliberately:

* sync functions run on the App's thread pool and must see the caller's
  contextvars;
* async functions run on the asyncio loop;
* a BaseException from a sync function must settle the Task;
* before ``run()`` both paths fail with ``RuntimeError`` instead of hanging;
* during the close negotiation (``CloseRequestedEvent``) both paths are still
  admitted;
* once ``run()`` returned (``STOPPED``) both paths fail with
  ``AppClosedError`` — the async path used to report ``RuntimeError``.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys

from lumiview import App, AppClosedError, AppEvent, task

_marker: contextvars.ContextVar[str] = contextvars.ContextVar(
    "marker", default="unset"
)

# Filled by the CloseRequestedEvent handler; asserted after run() returned so
# a failure there cannot be masked by the already-requested exit code.
close_results: list[object] = []


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

    # with_timeout: the wrapper fails, but the shared source keeps running.
    latch = app.wait_for(AppEvent.ReopenEvent)
    bounded = latch.with_timeout(0.05, message="latch timed out")
    try:
        await bounded
    except TimeoutError as exc:
        assert "latch timed out" in str(exc), exc
    else:
        raise AssertionError("with_timeout did not fire")
    app._emit(AppEvent.ReopenEvent(has_visible_windows=True))
    assert (await latch).has_visible_windows is True

    # A BaseException from a sync function must settle the Task instead of
    # leaving it pending forever.
    handle = task(_raise_keyboard_interrupt)
    try:
        await handle
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt did not reach the caller")

    @app.on(AppEvent.CloseRequestedEvent)
    async def _on_close(_event) -> None:
        # Nothing is committed while the handlers decide: both paths must be
        # admitted (cleanup work often needs them).
        close_results.append(await task(lambda: None))
        close_results.append(await task(_double, 1))

    app.exit(0)
    await asyncio.sleep(0.2)


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
    assert code == 0, f"run() returned {code}"
    assert close_results == [None, 2], close_results

    # After run() returned (STOPPED) both paths fail with AppClosedError.
    # Already settled, so ``exception()`` is a plain read (no blocking).
    for handle in (task(lambda: None), task(_double, 1)):
        exc = handle.exception()
        assert isinstance(exc, AppClosedError), (
            f"task() after shutdown returned {exc!r}, expected AppClosedError"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
