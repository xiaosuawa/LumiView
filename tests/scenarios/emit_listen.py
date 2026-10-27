"""webview: Python ``emit()`` → JS EventTarget → JS ``emit()`` round-trip.

The existing ``ipc_roundtrip_permission`` covers JS→Python *invoke*; this
covers events in both directions: Python dispatches on the dedicated
``window.lumiview`` EventTarget (isolated from DOM events), both the
``listen`` helper and a raw ``addEventListener`` receive it, and the page
pushes an acknowledgement back as a ``WindowEvent.JsEvent``.
"""

from __future__ import annotations

import sys

from lumiview import App, Task, Window, WindowEvent, WindowOptions, when


async def _entry() -> None:
    ack: Task | None = None

    def on_prepare(win: Window) -> None:
        nonlocal ack
        # Registered before the page can run, so the acknowledgement
        # cannot be missed.
        ack = win.wait_for(
            WindowEvent.JsEvent, where=when(event="test.ack"), timeout=20
        )

    win = await Window.create(WindowOptions(
        html="<html><body>"
             "<script>"
             "window.lumiview.listen('data.changed', (p) => {"
             "  window.__viaListen = p;"
             "});"
             "window.lumiview.addEventListener('data.changed', (e) => {"
             "  window.__viaNative = e.detail;"
             "  window.lumiview.emit('test.ack', e.detail);"
             "});"
             "</script>"
             "</body></html>",
        visible=False,
        prepare=on_prepare,
    ))
    await win.wait_loaded(timeout=20)

    await win.emit("data.changed", {"value": 42, "note": "hi"})

    assert ack is not None, "prepare never ran"
    event = await ack
    assert event.payload == {"value": 42, "note": "hi"}, event.payload

    # The same dispatch reached both the helper and the raw listener.
    via_listen = await win.eval_js("JSON.stringify(window.__viaListen)")
    via_native = await win.eval_js("JSON.stringify(window.__viaNative)")
    assert "42" in str(via_listen), f"listen got {via_listen!r}"
    assert "42" in str(via_native), f"addEventListener got {via_native!r}"
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
