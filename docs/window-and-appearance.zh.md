# 窗口管理与原生外观

## 常用状态与几何控制

所有原生控制方法均返回 `Task`（注意：属性 `win.id`、`win.is_closed`、`win.bridge` 为本地直接读取，无需 `await`）：

```python
# 尺寸与位置（逻辑像素）
await win.set_inner_size(1024, 720)
await win.set_outer_position(100, 100)
await win.set_min_inner_size(600, 400)
await win.set_max_inner_size(1920, 1080)
w, h = await win.inner_size()
sf = await win.scale_factor()

# 可见性与焦点
await win.show()                 # 显示并恢复最小化
await win.hide()                 # 隐藏窗口（sync_visibility=True 时同步隐藏 WebView 以节省 GPU/CPU）
await win.toggle_visibility()    # 切换显示/隐藏
await win.focus()                # 聚焦窗口

# 窗口状态
await win.set_minimized(True)
await win.set_maximized(True)
is_max = await win.toggle_maximize()
await win.set_fullscreen(True)   # 无边框全屏（也可调用 set_borderless_fullscreen / set_exclusive_fullscreen）

# 关闭请求与销毁
await win.request_close()        # 触发 CloseRequestedEvent，受 close_behavior 与 prevent() 控制
await win.close()                # 强制立即关闭并销毁资源
```

### 关闭行为 `CloseBehavior`

通过 `WindowOptions(close_behavior=...)` 配置收到关闭请求且未被 `prevent()` 时的默认行为：
- `CloseBehavior.Close`（默认）：销毁窗口
- `CloseBehavior.Hide`：隐藏窗口而不销毁
- `CloseBehavior.Ignore`：忽略请求

---

## 无边框窗口与自定义标题栏

LumiView 内置了第一方插件 `WindowControls`，无需自己手写复杂的拖拽判断逻辑。它位于独立子模块，
因此 `import lumiview` 不会加载插件代码：

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
    <!-- 声明式拖拽区域：单击拖动窗口，双击最大化/还原 -->
    <div style="flex:1;padding:0 12px;" data-lumiview-drag-region>
      <span>LumiView</span>
      <!-- 子元素带有 data-lumiview-no-drag 或交互标签(button/a/input等)不会触发拖动 -->
      <span data-lumiview-no-drag>状态正常</span>
    </div>
    <button onclick="__LUMIVIEW__.plugins.window.minimize()">最小化</button>
    <button onclick="__LUMIVIEW__.plugins.window.toggleMaximize()">最大化</button>
    <button onclick="__LUMIVIEW__.plugins.window.close()">关闭</button>
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

### `WindowControls` 细节说明

- **插件挂载命名空间**：页面 JS 接口挂载在 `window.__LUMIVIEW__.plugins.<name>`，默认 `name="window"`，提供：
  - `minimize()` / `toggleMaximize()` / `isMaximized()` / `close()`
  - `onMaximizedChange((maximized) => ...)`：监听最大化状态变化并同步到页面
  - `startDragging()` / `startResizeDragging(direction)`
- **缩放热区**：无边框窗口的 8 个系统边缘拉伸在底层已自动支持，通常无需手动标注；如果要在页面**内部**制作分隔条缩放手柄，可使用 `data-lumiview-resize-region="east"`（支持 `east`、`north`、`south`、`west` 及 `north-east` 等组合）。
- **全屏状态同步**：`link_fullscreen=True`（默认）时，网页内触发 HTML5 Fullscreen API 会自动同步给原生窗口。

---

## 原生背景特效与 macOS 标题栏

### 背景材质：`WindowEffect`

- `await win.apply_effect(effect, color=None, material=None)`
  - **Windows**：支持 `WindowEffect.Blur`、`WindowEffect.Acrylic`（可传 `color=(r, g, b, a)`）、`WindowEffect.Mica`。通常需搭配 `transparent=True`。
  - **macOS**：支持 `WindowEffect.Vibrancy`，可通过 `material=VibrancyMaterial.Sidebar`（或 `HudWindow`、`UnderWindowBackground` 等）指定毛玻璃材质。
  - 当前系统或版本不支持时抛出 `NotImplementedError`。
- `await win.clear_effect(effect)`：清除已应用的材质。

### macOS 标题栏定制：`TitleBarOptions`

在 macOS 上可通过 `WindowOptions(titlebar=TitleBarOptions(...))` 实现现代原生样式（如交通灯内嵌、内容延伸至标题栏下方，其他平台自动忽略）：

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

## 图标、主题、鼠标与任务栏

- **图标**：`WindowOptions(icon=...)` 与 `await win.set_icon(...)` 支持三种格式：
  1. `(rgba_bytes, width, height)` 元组（零额外依赖）
  2. 图片文件路径字符串（需安装 `Pillow`）
  3. `PIL.Image.Image` 对象（需安装 `Pillow`）
- **主题**：`await win.set_theme(Theme.Dark)`（或 `Theme.Light` / `None` 跟随系统）。窗口边框全平台生效，WebView 网页媒体查询主题切换仅 Windows WebView2 支持，macOS/Linux 跟随系统。
- **鼠标交互**：`set_cursor_icon(CursorIcon)`、`set_cursor_visible(bool)`、`set_cursor_grab(bool)`、`set_ignore_cursor_events(bool)`（鼠标穿透）。
- **任务栏进度与提醒**：`await win.set_progress_bar(ProgressState.Normal, 65.0)`（Windows），`await win.request_user_attention(AttentionType.Informational)`。
- **平台专属方法**：如 `set_skip_taskbar`（Windows/Linux）、`set_badge_label`（macOS）、`set_badge_count`（Linux）等；若在不支持的平台上调用，返回的 `Task` 会以 `NotImplementedError` 失败。

---

## WebView 浏览器能力

- **开发者工具**：`await win.open_devtools()` / `close_devtools()` / `is_devtools_open()`
- **缩放与打印**：`await win.zoom(1.25)`、`await win.print()`
- **Cookie 与缓存**：
  - `await win.cookies()` / `await win.cookies_for_url(url)`
  - `await win.set_cookie(name, value, domain=..., path=...)`
  - `await win.delete_cookie(name, url)`
  - `await win.clear_all_browsing_data()`
