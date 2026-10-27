"""app: App.wait_for — one-shot resolution, where=, timeout, shutdown."""

from __future__ import annotations

import sys

from lumiview import App, AppEvent
from lumiview.app import AppClosedError


async def _entry() -> None:
    app = App.get()

    # One-shot: resolves with the dispatched event and unregisters.
    pending = app.wait_for(AppEvent.ReopenEvent, timeout=10)
    app._emit(AppEvent.ReopenEvent(has_visible_windows=False))
    event = await pending
    assert isinstance(event, AppEvent.ReopenEvent), event

    # where= filters non-matching events out.
    filtered = app.wait_for(
        AppEvent.ReopenEvent,
        where=lambda e: e.has_visible_windows,
        timeout=10,
    )
    app._emit(AppEvent.ReopenEvent(has_visible_windows=False))
    app._emit(AppEvent.ReopenEvent(has_visible_windows=True))
    event = await filtered
    assert event.has_visible_windows is True, event

    # Timeout.
    try:
        await app.wait_for(AppEvent.ReopenEvent, timeout=0.05)
    except TimeoutError:
        pass
    else:
        raise AssertionError("wait_for timeout did not fire")

    app.exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)

    # Before run(): no loop yet — a failed Task, never a raise.
    early = app.wait_for(AppEvent.ReopenEvent)
    assert early.done() and isinstance(early.exception(), RuntimeError), early

    code = app.run(_entry)
    assert code == 0, f"run() returned {code}"

    # After shutdown: a failed Task with AppClosedError.
    late = App.get().wait_for(AppEvent.ReopenEvent)
    assert late.done() and isinstance(late.exception(), AppClosedError), late
    return 0


if __name__ == "__main__":
    sys.exit(main())
