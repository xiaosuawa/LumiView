from __future__ import annotations

import sys

from lumiview import App, Window, WindowOptions


async def _entry() -> None:
    # Create the windows one at a time, waiting for each page before the
    # next WebView2 is constructed. Two WebView2 instances initializing
    # concurrently intermittently hang on Windows (the second `WebView`
    # constructor never returns), while both windows still stay alive
    # together — which is what this scenario verifies.
    print("[scenario] create win1", flush=True)
    win1 = await Window.create(WindowOptions(
        html="<html><body><h1>one</h1></body></html>",
        visible=False,
    ))
    print("[scenario] wait win1 loaded", flush=True)
    await win1.wait_loaded(timeout=20)

    print("[scenario] create win2", flush=True)
    win2 = await Window.create(WindowOptions(
        html="<html><body><h1>two</h1></body></html>",
        visible=False,
    ))
    print("[scenario] wait win2 loaded", flush=True)
    await win2.wait_loaded(timeout=20)

    print("[scenario] eval_js", flush=True)
    v1 = await win1.eval_js("document.querySelector('h1').textContent")
    v2 = await win2.eval_js("document.querySelector('h1').textContent")
    assert "one" in str(v1), f"win1 text {v1!r}"
    assert "two" in str(v2), f"win2 text {v2!r}"
    assert len(App.get()._windows) == 2, f"expected 2 windows, got {len(App.get()._windows)}"
    print("[scenario] exit", flush=True)
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
