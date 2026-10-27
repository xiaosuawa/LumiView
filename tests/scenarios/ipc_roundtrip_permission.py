from __future__ import annotations

import sys

from lumiview import (
    App,
    Bridge,
    BridgeContext,
    ScopePermission,
    Task,
    Window,
    WindowEvent,
    WindowOptions,
    when,
)

bridge = Bridge(permissions=ScopePermission(allow=("ping",)))


@bridge.command
def ping(_ctx: BridgeContext, n: int) -> int:
    return n + 1


@bridge.command
def secret(_ctx: BridgeContext) -> str:
    return "classified"


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
            "Promise.all(["
            "  window.lumiview.invoke('ping', {n: 41})"
            "    .then(v => ({ping: v}))"
            "    .catch(e => ({ping: 'ERR:' + e.code})),"
            "  window.lumiview.invoke('secret')"
            "    .then(v => ({secret: v}))"
            "    .catch(e => ({secret: 'ERR:' + e.code})),"
            "]).then(r => window.lumiview.emit('test.done', Object.assign({}, ...r)));"
            "</script></body></html>"
        ),
        visible=False,
        bridge=bridge,
        prepare=on_prepare,
    ))
    await win.wait_loaded(timeout=20)

    assert done is not None, "prepare never ran"
    event = await done
    results = event.payload

    assert "42" in str(results.get("ping")), f"ping returned {results!r}"
    assert "forbidden" in str(results.get("secret")), f"secret returned {results!r}"
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
