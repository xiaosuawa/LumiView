"""
custom_titlebar.py — Frameless window with custom titlebar and native effects.

Shows:
  - decorations=False — hide the system titlebar
  - transparent=True — transparent window background
  - window_controls=True — enable lumiview.window.* JS API
  - data-lumiview-drag-region — declarative drag area
  - apply_effect() — native window material (Acrylic / Mica / Vibrancy)

Run:
    python examples/custom_titlebar.py
"""

import sys

from lumiview import App, Window, WindowEffect

app = App(name="CustomTitlebar")

HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Custom Titlebar</title></head>
<style>
  html, body { margin: 0; background: transparent; font-family: sans-serif; }
  .frame { min-height: 100vh; background: rgba(24, 28, 36, .72);
           color: #cdd6f4; display: flex; flex-direction: column; }
  .titlebar { height: 44px; display: flex; align-items: center; }
  .drag { flex: 1; padding: 0 14px; user-select: none; }
  button { width: 46px; height: 44px; border: 0; color: #cdd6f4;
           background: transparent; cursor: pointer; font-size: 16px; }
  button:hover { background: rgba(255, 255, 255, .12); }
  .content { flex: 1; display: flex; align-items: center; justify-content: center;
             font-size: 24px; user-select: none; }
</style>
<div class="frame">
  <header class="titlebar">
    <div class="drag" data-lumiview-drag-region>
      <span style="font-weight:600;">LumiView</span>
    </div>
    <button onclick="lumiview.window.minimize()" title="Minimize">&#x2014;</button>
    <button onclick="lumiview.window.toggleMaximize()" title="Maximize">&#9744;</button>
    <button onclick="lumiview.window.close()" title="Close">&#x2715;</button>
  </header>
  <div class="content">
    Drag here to move the window
  </div>
</div>
</html>"""


async def main():
    win = await Window.create(
        title="Custom Titlebar",
        html=HTML,
        width=760,
        height=520,
        decorations=False,          # no system titlebar
        transparent=True,           # transparent window background
        window_controls=True,       # enable JS window control API
        background_color=(0, 0, 0, 0),
    )

    # Try to apply a native window effect
    effect = (
        WindowEffect.Acrylic if sys.platform == "win32"
        else WindowEffect.Vibrancy
    )
    try:
        await win.apply_effect(effect)
    except NotImplementedError as exc:
        print(f"Native material unavailable: {exc}")


if __name__ == "__main__":
    app.run(main)
