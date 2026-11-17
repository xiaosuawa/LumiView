from __future__ import annotations

import asyncio
import sys

from lumiview import App, AppEvent

order: list[str] = []


async def _entry() -> None:
    order.append("entry")
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)

    @app.on(AppEvent.ReadyEvent)
    async def on_ready(_event) -> None:
        # Yield to the loop: proves entry waits for every Ready handler to finish.
        await asyncio.sleep(0)
        order.append("ready")

    @app.on(AppEvent.ReadyEvent)
    async def on_ready_raises(_event) -> None:
        order.append("boom")
        raise RuntimeError("ready handler failed")

    code = app.run(_entry)
    assert code == 0, f"run() returned {code} (a failing Ready handler must not abort)"
    assert order == ["ready", "boom", "entry"], f"unexpected order: {order!r}"
    return 0


if __name__ == "__main__":
    sys.exit(main())
