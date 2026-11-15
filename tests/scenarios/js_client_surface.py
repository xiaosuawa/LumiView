"""bridge: the injected client surface (``window.__LUMIVIEW__``).

Locks the contract that replaced ``window.lumiview``:

- the old global is gone;
- ``__LUMIVIEW__`` exists, is non-enumerable and cannot be replaced;
- its core methods are read-only, so page code cannot hijack ``dispatch``;
- ``invoke()`` still round-trips through the same object.
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
)

PAGE = """\
<script>
  (async () => {
    const out = {
      legacy: typeof window.lumiview,
      own: "__LUMIVIEW__" in window,
      enumerable: Object.keys(window).includes("__LUMIVIEW__"),
    };
    const client = window.__LUMIVIEW__;
    out.versioned = typeof client.v === "number" && client.v >= 1;
    out.build = typeof client.build === "string" && client.build.length > 0;

    // Sloppy mode: assignment to a non-writable property fails silently.
    window.__LUMIVIEW__ = {};
    out.clientKept = window.__LUMIVIEW__ === client;

    const originalDispatch = client.dispatch;
    client.dispatch = () => {};
    out.dispatchKept = client.dispatch === originalDispatch;

    try {
      out.result = await client.invoke("ping");
    } catch (error) {
      out.error = String((error && error.message) || error);
    }
    client.emit("test.done", out);
  })();
</script>
"""


async def _entry() -> None:
    bridge = Bridge()

    @bridge.command
    def ping(_ctx: BridgeContext) -> str:
        return "pong"

    done: Task | None = None

    def on_prepare(win: Window) -> None:
        nonlocal done
        done = win.wait_for(
            WindowEvent.JsEvent, where=lambda e: e.event == "test.done", timeout=20
        )

    win = await Window.create(
        WindowOptions(
            html=f"<html><body>{PAGE}</body></html>",
            visible=False,
            bridge=bridge,
            prepare=on_prepare,
        )
    )
    await win.wait_loaded(timeout=20)

    assert done is not None, "prepare never ran"
    out = (await done).payload

    assert out.get("legacy") == "undefined", out
    assert out.get("own") is True, out
    assert out.get("enumerable") is False, out
    assert out.get("versioned") is True, out
    assert out.get("build") is True, out
    assert out.get("clientKept") is True, out
    assert out.get("dispatchKept") is True, out
    assert out.get("result") == "pong", out
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
