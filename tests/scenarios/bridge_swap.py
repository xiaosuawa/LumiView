"""bridge: ``Window.bridge`` is public and can be swapped at runtime.

A window is created with ``bridge_a`` (command ``alpha``). After the
page loads, Python replaces ``win.bridge`` with ``bridge_b`` (command
``beta``); the page then probes both. The new object's command tree
takes effect immediately and the old command is gone.
"""

from __future__ import annotations

import sys

from lumiview import (
    App,
    Bridge,
    BridgeContext,
    Task,
    Window,
    WindowEvent,
    WindowOptions,
    when,
)

bridge_a = Bridge()


@bridge_a.command
def alpha(_ctx: BridgeContext) -> str:
    return "A"


bridge_b = Bridge()


@bridge_b.command
def beta(_ctx: BridgeContext) -> str:
    return "B"


async def _entry() -> None:
    done: Task | None = None

    def on_prepare(win: Window) -> None:
        nonlocal done
        done = win.wait_for(
            WindowEvent.JsEvent, where=when(event="test.done"), timeout=20
        )

    win = await Window.create(WindowOptions(
        html=(
            "<html><body><script>"
            "window.lumiview.listen('test.go', async () => {"
            "  const out = {};"
            "  for (const name of ['alpha', 'beta']) {"
            "    try { out[name] = await window.lumiview.invoke(name); }"
            "    catch (e) { out[name] = 'ERR:' + e.code; }"
            "  }"
            "  window.lumiview.emit('test.done', out);"
            "});"
            "</script></body></html>"
        ),
        visible=False,
        bridge=bridge_a,
        prepare=on_prepare,
    ))
    await win.wait_loaded(timeout=20)

    # Runtime swap — subsequent invokes use bridge_b's command tree.
    win.bridge = bridge_b
    await win.emit("test.go")

    assert done is not None, "prepare never ran"
    event = await done
    results = event.payload
    assert results.get("alpha") == "ERR:unknown_command", results
    assert results.get("beta") == "B", results
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
