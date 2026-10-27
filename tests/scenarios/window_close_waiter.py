"""window: closing a window dispatches ClosedEvent and fails waiters.

Covers the explicit ``Window.close()`` path (app shutdown is covered by
``window_waiter_on_shutdown``) and registration after the window is gone.
"""

from __future__ import annotations

import sys

from lumiview import App, Window, WindowEvent, WindowOptions
from lumiview.app import WindowClosedError

closed_events: list = []


async def _entry() -> None:
    win = await Window.create(
        WindowOptions(html="<html><body></body></html>", visible=False)
    )
    win.on(WindowEvent.ClosedEvent)(closed_events.append)

    # Pending waiter fails when the window closes.
    waiter = win.wait_for(WindowEvent.ReceivedImeTextEvent, timeout=10)
    await win.close()
    try:
        await waiter
    except WindowClosedError:
        pass
    else:
        raise AssertionError("pending wait_for did not fail on close")

    # Registering after the close returns an already-failed Task.
    late = win.wait_for(WindowEvent.TitleChangedEvent)
    try:
        await late
    except WindowClosedError:
        pass
    else:
        raise AssertionError("wait_for after close did not fail")

    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    assert code == 0, f"run() returned {code}"
    assert closed_events, "WindowEvent.ClosedEvent was not dispatched"
    return 0


if __name__ == "__main__":
    sys.exit(main())
