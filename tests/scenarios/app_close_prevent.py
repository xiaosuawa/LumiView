"""app: CloseRequestedEvent.prevent() cancels an exit and the app keeps running.

The veto must leave the app fully usable — windows still open, the state
still ``RUNNING``, no recorded exit code — and a later ``exit()`` must start a
fresh close phase.
"""

from __future__ import annotations

import asyncio
import sys

from lumiview import App, AppEvent, AppState, Window, WindowOptions

calls: list[bool] = []


async def _entry() -> None:
    app = App.get()
    win = await Window.create(
        WindowOptions(html="<html><body>dirty</body></html>", visible=False)
    )

    @app.on(AppEvent.CloseRequestedEvent)
    async def _on_close(event) -> None:
        calls.append(app.is_running)
        if len(calls) == 1:
            # Pretend the user chose "keep working" in a save dialog.
            event.prevent()

    app.exit(0)
    await asyncio.sleep(0.2)  # let the close phase run and roll back

    assert app.state is AppState.RUNNING, app.state
    assert app.is_running and not app.is_stopped
    assert win in app.windows
    await win.set_title("still running")  # the whole API works after a veto

    # The veto reset the negotiation flag: a fresh exit() must negotiate
    # again instead of being treated as a duplicate request.
    app.exit(7)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    assert code == 7, f"run() returned {code} (a prevented exit must not count)"
    assert calls == [True, True], calls
    return 0


if __name__ == "__main__":
    sys.exit(main())
