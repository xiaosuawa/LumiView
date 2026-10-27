"""window: ClosedEvent is dispatched and pending waiters fail on shutdown.

The app-level teardown force-closes windows without going through
``Window.close()``; it must still dispatch ``WindowEvent.ClosedEvent`` so
waiters do not hang past ``run()``.
"""

from __future__ import annotations

import asyncio
import sys

from lumiview import App, Window, WindowEvent, WindowOptions
from lumiview.app import WindowClosedError

outcomes: list[BaseException] = []
closed_events: list = []


async def _entry() -> None:
    win = await Window.create(
        WindowOptions(html="<html><body></body></html>", visible=False)
    )
    win.on(WindowEvent.ClosedEvent)(closed_events.append)
    waiter = win.wait_for(WindowEvent.ReceivedImeTextEvent, timeout=30)
    waiter.on_exception(outcomes.append)
    App.get().exit(0)
    await asyncio.sleep(0.2)  # shutdown force-closes the window meanwhile


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    assert code == 0, f"run() returned {code}"
    assert closed_events, "WindowEvent.ClosedEvent was not dispatched"
    assert any(isinstance(exc, WindowClosedError) for exc in outcomes), outcomes
    return 0


if __name__ == "__main__":
    sys.exit(main())
