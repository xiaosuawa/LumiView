from __future__ import annotations

import sys

from lumiview import App, AppEvent

ran: set[str] = set()


async def _entry() -> None:
    ran.add("entry")
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)

    @app.on(AppEvent.ReadyEvent)
    async def on_ready(_event) -> None:
        ran.add("ready")

    code = app.run(_entry)
    assert code == 0, f"run() returned {code}"
    assert ran == {"ready", "entry"}, f"expected both hooks to run, got {ran!r}"
    return 0


if __name__ == "__main__":
    sys.exit(main())
