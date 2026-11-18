# Window management and native appearance

## Common state and geometry controls

Every native control method returns a `Task` (note that `win.id`, `win.is_closed` and
`win.bridge` are local reads — no `await` needed):

```python
# size and position (logical pixels)
await win.set_inner_size(1024, 720)
await win.set_outer_position(100, 100)
await win.set_min_inner_size(600, 400)
await win.set_max_inner_size(1920, 1080)
w, h = await win.inner_size()
sf = await win.scale_factor()

# visibility and focus
await win.show()                 # show and restore from minimized
await win.hide()                 # hide the window (with sync_visibility=True the WebView hides too, saving GPU/CPU)
await win.toggle_visibility()    # toggle visibility
await win.focus()                # focus the window

# window state
await win.set_minimized(True)
await win.set_maximized(True)
is_max = await win.toggle_maximize()
await win.set_fullscreen(True)   # borderless fullscreen (or call set_borderless_fullscreen / set_exclusive_fullscreen)

# close requests and destruction
await win.request_close()        # dispatches CloseRequestedEvent; close_behavior and prevent() decide the outcome
await win.close()                # close immediately and destroy resources
```

### Close behavior: `CloseBehavior`

`WindowOptions(close_behavior=...)` sets what happens when a close request arrives and
no handler calls `prevent()`:
- `CloseBehavior.Close` (default): destroys the window
- `CloseBehavior.Hide`: hides the window without destroying it
- `CloseBehavior.Ignore`: ignores the request

---

## Frameless windows and custom titlebars

LumiView ships a first-party `WindowControls` Plugin, so you do not have to hand-write
the drag hit-testing logic. It lives in its own submodule so importing `lumiview` does not
load the plugin:

```python
import sys
from lumiview import App, Bridge, Window, WindowEffect, WindowOptions
from lumiview.plugins.window_controls import WindowControls

app = App(name="CustomTitlebar")
bridge = Bridge(includes=[WindowControls(drag_regions=True)])

HTML = """<!doctype html>
<html>
<body style="margin:0;background:transparent;">
  <header style="height:40px;display:flex;align-items:center;background:rgba(24,28,36,0.75);color:#fff;">
    <!-- declarative drag region: click-drag moves the window, double-click maximizes/restores -->
    <div style="flex:1;padding:0 12px;" data-lumiview-drag-region>
      <span>LumiView</span>
      <!-- children with data-lumiview-no-drag or interactive tags (button/a/input etc.) never start a drag -->
      <span data-lumiview-no-drag>Status OK</span>
    </div>
    <button onclick="__LUMIVIEW__.plugins.window.minimize()">Minimize</button>
    <button onclick="__LUMIVIEW__.plugins.window.toggleMaximize()">Maximize</button>
    <button onclick="__LUMIVIEW__.plugins.window.close()">Close</button>
  </header>
</body>
</html>"""


async def main():
    win = await Window.create(
        WindowOptions(
            html=HTML,
            decorations=False,
            transparent=True,
            background_color=(0, 0, 0, 0),
            bridge=bridge,
        )
    )

    effect = WindowEffect.Acrylic if sys.platform == "win32" else WindowEffect.Vibrancy
    try:
        await win.apply_effect(effect)
    except NotImplementedError:
        pass


app.run(main)
```

### `WindowControls` details

- **Plugin mount namespace**: the page-side JS API lives at
  `window.__LUMIVIEW__.plugins.<name>`, with `name="window"` by default, and
  provides:
  - `minimize()` / `toggleMaximize()` / `isMaximized()` / `close()`
  - `onMaximizedChange((maximized) => ...)`: watches maximize-state changes and syncs
    them to the page
  - `startDragging()` / `startResizeDragging(direction)`
- **Resize hot zones**: the 8 system edge-resize handles of a frameless window are
  wired up in the native layer, so you usually do not need to annotate them; to build
  a splitter resize handle **inside** the page, use
  `data-lumiview-resize-region="east"` (`east`, `north`, `south`, `west` and
  combinations such as `north-east` are supported).
- **Fullscreen state sync**: with `link_fullscreen=True` (the default), entering
  fullscreen through the HTML5 Fullscreen API is synced to the native window
  automatically.

---

## Native background effects and macOS titlebars

### Background material: `WindowEffect`

- `await win.apply_effect(effect, color=None, material=None)`
  - **Windows**: supports `WindowEffect.Blur`, `WindowEffect.Acrylic` (which accepts
    `color=(r, g, b, a)`) and `WindowEffect.Mica`. Usually paired with
    `transparent=True`.
  - **macOS**: supports `WindowEffect.Vibrancy`; use
    `material=VibrancyMaterial.Sidebar` (or `HudWindow`, `UnderWindowBackground`, ...)
    to choose the blur material.
  - Raises `NotImplementedError` when the current OS or version does not support it.
- `await win.clear_effect(effect)`: removes an applied material.

### macOS titlebar customization: `TitleBarOptions`

On macOS, `WindowOptions(titlebar=TitleBarOptions(...))` gives you the modern native
style — inset traffic lights, content extending beneath the titlebar — and is ignored
on other platforms:

```python
from lumiview import TitleBarOptions, WindowOptions

opts = WindowOptions(
    titlebar=TitleBarOptions(
        transparent=True,
        title_hidden=True,
        fullsize_content_view=True,
        traffic_light_inset=(14.0, 18.0),
        movable_by_background=False,
    )
)
```

---

## Icons, themes, mouse and taskbar

- **Icons**: `WindowOptions(icon=...)` and `await win.set_icon(...)` accept three
  formats:
  1. a `(rgba_bytes, width, height)` tuple (no extra dependencies)
  2. an image file path string (requires `Pillow`)
  3. a `PIL.Image.Image` object (requires `Pillow`)
- **Theme**: `await win.set_theme(Theme.Dark)` (or `Theme.Light` / `None` to follow
  the system). Window chrome updates on every platform; switching the WebView's CSS
  media-query theme is supported only by WebView2 on Windows, while macOS/Linux follow
  the system.
- **Mouse interaction**: `set_cursor_icon(CursorIcon)`, `set_cursor_visible(bool)`,
  `set_cursor_grab(bool)`, `set_ignore_cursor_events(bool)` (click-through).
- **Taskbar progress and attention**: `await win.set_progress_bar(ProgressState.Normal, 65.0)`
  (Windows), `await win.request_user_attention(AttentionType.Informational)`.
- **Platform-specific methods**: such as `set_skip_taskbar` (Windows/Linux),
  `set_badge_label` (macOS) and `set_badge_count` (Linux); calling one on an
  unsupported platform makes the returned `Task` fail with `NotImplementedError`.

---

## WebView browser capabilities

- **DevTools**: `await win.open_devtools()` / `close_devtools()` / `is_devtools_open()`
- **Zoom and printing**: `await win.zoom(1.25)`, `await win.print()`
- **Cookies and cache**:
  - `await win.cookies()` / `await win.cookies_for_url(url)`
  - `await win.set_cookie(name, value, domain=..., path=...)`
  - `await win.delete_cookie(name, url)`
  - `await win.clear_all_browsing_data()`
