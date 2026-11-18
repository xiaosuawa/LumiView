"""plugins: WindowControls JS namespaces and per-page install markers.

Two instances are mounted on one bridge: the default (``window``) and a named
one (``titlebar``). The page checks that both namespaces exist with the full
method set, that the drag-region script installed itself once (via its
``Symbol.for`` marker rather than a public property), and that
``plugins.titlebar.close()`` actually closes the window.
"""

from __future__ import annotations

import json
import sys

from lumiview import App, Bridge, Window, WindowEvent, WindowOptions
from lumiview.plugins.window_controls import WindowControls

METHODS = [
    "close",
    "isMaximized",
    "minimize",
    "onMaximizedChange",
    "startDragging",
    "startResizeDragging",
    "toggleMaximize",
]

PAGE = """<html><body>
<div data-lumiview-drag-region style="height:40px">drag</div>
<script>
(async () => {
  const client = window.__LUMIVIEW__;
  const describe = (ns) => {
    const api = client.plugins[ns];
    return { present: typeof api === "object", methods: api ? Object.keys(api).sort() : [] };
  };
  client.emit("surface", {
    defaultNs: describe("window"),
    namedNs: describe("titlebar"),
    namespaces: Object.keys(client.plugins).sort(),
    dragInstalled: Symbol.for("lumiview.dragRegions") in client,
    // Implementation markers must not leak into the public surface.
    publicKeys: Object.keys(client).sort(),
  });
})();
</script></body></html>"""


async def _entry() -> None:
    bridge = Bridge(includes=[WindowControls(), WindowControls(name="titlebar")])

    surface = None

    def prepare(win: Window) -> None:
        nonlocal surface
        surface = win.wait_for(
            WindowEvent.JsEvent, where=lambda e: e.event == "surface", timeout=20
        )

    win = await Window.create(
        WindowOptions(
            html=PAGE,
            visible=False,
            decorations=False,
            bridge=bridge,
            prepare=prepare,
        )
    )
    await win.wait_loaded(timeout=20)

    assert surface is not None, "prepare never ran"
    out = (await surface).payload

    assert out["defaultNs"] == {"present": True, "methods": METHODS}, out
    assert out["namedNs"] == {"present": True, "methods": METHODS}, out
    assert out["namespaces"] == ["titlebar", "window"], out
    assert out["dragInstalled"] is True, out
    assert out["publicKeys"] == [
        "BridgeError",
        "addEventListener",
        "build",
        "dispatch",
        "emit",
        "invoke",
        "listen",
        "plugins",
        "removeEventListener",
        "v",
    ], out

    closed = win.wait_for(WindowEvent.ClosedEvent, timeout=20)
    await win.eval_js("window.__LUMIVIEW__.plugins.titlebar.close()")
    await closed

    print("[scenario] namespaces:", json.dumps(out["namespaces"]))
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
