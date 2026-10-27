"""webview: untrusted mode injects no bridge script; raw postMessage surfaces.

A single ``untrusted=True`` window carries no ``window.lumiview`` (the
BRIDGE_SCRIPT is not injected), but ``window.ipc.postMessage`` still routes a
raw message into ``WindowEvent.WebMessageReceivedEvent``.
"""

from __future__ import annotations

import asyncio
import sys

from lumiview import App, Window, WindowEvent, WindowOptions


async def _entry() -> None:
    got = asyncio.Event()
    messages: list[str] = []

    def on_prepare(win: Window) -> None:
        async def on_message(event) -> None:
            messages.append(event.message)
            got.set()

        win.on(WindowEvent.WebMessageReceivedEvent)(on_message)

    win = await Window.create(
        WindowOptions(
            html="<html><body></body></html>",
            visible=False,
            untrusted=True,
            bridge=None,
            prepare=on_prepare,
        )
    )
    # Wait for the page to attach before probing it — no sleep, no race.
    await win.wait_loaded(timeout=20)

    kind = await win.eval_js("typeof window.lumiview")
    assert "undefined" in str(kind), f"typeof window.lumiview = {kind!r}"

    # Even without the bridge script, wryview's own IPC channel still delivers
    # raw page messages to the Python side.
    await win.eval_js("window.ipc.postMessage('raw-msg-123'); 'go'")
    await asyncio.wait_for(got.wait(), timeout=15)
    assert any("raw-msg-123" in m for m in messages), messages
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
