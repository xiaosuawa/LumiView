"""webview: load inline html, then ``eval_js`` round-trips a page value.

Builds a real Window (spawning the platform engine — WebView2 / WKWebKit /
WebKitGTK), waits for the page to actually load, then reads a value back via
``eval_js`` — proving the engine renders and the Python<->JS bridge works.
"""

from __future__ import annotations

import sys

from lumiview import App, Window, WindowOptions


async def _entry() -> None:
    win = await Window.create(
        WindowOptions(
            html="<html><body><h1 id='x'>hi</h1></body></html>",
            visible=False,
            bridge=None,
        )
    )
    # Pre-registered latch — safe to await after create(), no race.
    await win.wait_loaded(timeout=20)
    val = await win.eval_js("document.getElementById('x').textContent")
    assert "hi" in str(val), f"eval_js returned {val!r}"
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
