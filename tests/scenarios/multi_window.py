from __future__ import annotations

import sys

from lumiview import App, Window, WindowOptions


async def _entry() -> None:
    win1 = await Window.create(WindowOptions(
        html="<html><body><h1>one</h1></body></html>",
        visible=False,
    ))
    win2 = await Window.create(WindowOptions(
        html="<html><body><h1>two</h1></body></html>",
        visible=False,
    ))

    await win1.wait_loaded(timeout=20)
    await win2.wait_loaded(timeout=20)

    v1 = await win1.eval_js("document.querySelector('h1').textContent")
    v2 = await win2.eval_js("document.querySelector('h1').textContent")
    assert "one" in str(v1), f"win1 text {v1!r}"
    assert "two" in str(v2), f"win2 text {v2!r}"
    assert len(App.get()._windows) == 2, f"expected 2 windows, got {len(App.get()._windows)}"
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
