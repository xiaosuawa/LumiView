"""app: CloseRequestedEvent -> teardown -> ClosedEvent, in that order.

``CloseRequestedEvent`` must be dispatched **first** — nothing torn down,
the main thread still draining commands, the asyncio loop still running — so
cleanup handlers can save window state, flush the page or ask the user.
Only after they return are the windows closed (``WindowEvent.ClosedEvent``),
then the app-level ``ClosedEvent`` fires, and finally the asyncio loop is
stopped, which must run the ``finally`` blocks of the tasks it cancels.
"""

from __future__ import annotations

import asyncio
import sys

from lumiview import (
    App,
    AppClosedError,
    AppEvent,
    AppState,
    Task,
    Window,
    WindowEvent,
    WindowOptions,
    task,
)

EXIT_CODE = 3
order: list[str] = []
pending_waiters: list[Task] = []
closed_waiters: list[Task] = []
closed_codes: list[int] = []


async def _entry() -> None:
    app = App.get()
    win = await Window.create(
        WindowOptions(html="<html><body><h1 id='x'>hi</h1></body></html>", visible=False)
    )
    await win.wait_loaded(timeout=20)

    async def _background() -> None:
        try:
            await asyncio.sleep(30)
        finally:
            order.append("task-finally")

    asyncio.ensure_future(_background())

    @app.on(AppEvent.CloseRequestedEvent)
    async def _on_close(event) -> None:
        # Nothing is torn down and nothing is refused; the app is still
        # RUNNING, so "is_running" answers "the native loop is alive".
        assert app.state is AppState.RUNNING, app.state
        assert app.is_running and not app.is_stopped
        assert not win.is_closed
        assert win in app.windows, app.windows
        order.append("close-requested")
        await win.set_title("closing")
        assert await app.call_on_main(lambda: "ok") == "ok"
        # Blocking cleanup still runs on the thread pool.
        assert await task(lambda: "pool-ok") == "pool-ok"
        # Needs the native loop to pump (the script result comes back
        # through the WebView's UI-thread callback).
        assert "hi" in str(await win.eval_js("document.getElementById('x').textContent"))
        # Creating a window during the negotiation works too — it is torn
        # down by the close unless the exit is prevented.
        extra = await Window.create(WindowOptions(html="<html></html>", visible=False))
        await extra.close()
        # App events keep flowing, so wait_for() still works here...
        reopened = app.wait_for(AppEvent.ReopenEvent, timeout=5)
        app._emit(AppEvent.ReopenEvent(has_visible_windows=False))
        assert isinstance(await reopened, AppEvent.ReopenEvent)
        # ...and a waiter still pending when the app closes fails.
        pending_waiters.append(app.wait_for(AppEvent.ReopenEvent))
        # A waiter for ClosedEvent itself resolves with the event.
        closed_waiters.append(app.wait_for(AppEvent.ClosedEvent, timeout=10))

    @app.on(AppEvent.ClosedEvent)
    async def _on_closed(event) -> None:
        # The irreversible half: state flipped, native side already gone.
        assert app.is_stopped, app.state
        assert app.is_stopped and not app.is_running
        closed_codes.append(event.exit_code)
        order.append("app-closed")

    async def _on_window_closed(_event) -> None:
        order.append("window-closed")

    win.on(WindowEvent.ClosedEvent, _on_window_closed)

    app.exit(EXIT_CODE)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    assert code == EXIT_CODE, f"run() returned {code}"
    assert order == [
        "close-requested",
        "window-closed",
        "app-closed",
        "task-finally",
    ], order
    assert closed_codes == [EXIT_CODE], closed_codes
    assert App.get().is_stopped
    # The waiter registered during the close phase was failed when the app
    # closed (ClosedEvent is the "owner closed" signal, like the window one).
    assert len(pending_waiters) == 1
    late_waiter = pending_waiters[0]
    assert late_waiter.done() and isinstance(
        late_waiter.exception(), AppClosedError
    ), late_waiter
    # ... while a waiter for ClosedEvent itself resolved with the event.
    assert len(closed_waiters) == 1
    closed_event = closed_waiters[0].result(timeout=1)
    assert isinstance(closed_event, AppEvent.ClosedEvent), closed_event
    assert closed_event.exit_code == EXIT_CODE, closed_event.exit_code
    # The native loop is gone: main-thread work fails instead of hanging.
    late = App.get().call_on_main(lambda: None)
    assert late.done() and isinstance(late.exception(), AppClosedError), late
    # ... and so does new work.
    late_task = task(lambda: None)
    assert late_task.done() and isinstance(late_task.exception(), AppClosedError)
    return 0


if __name__ == "__main__":
    sys.exit(main())
