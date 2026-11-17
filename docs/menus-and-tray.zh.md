# 原生菜单与系统托盘

LumiView 集成了 `muda`（原生菜单）与 `tray-icon`（系统托盘），菜单项和托盘配置均为**纯数据对象**，可以在 `App.run()` 之前在任意线程构造，随后统一在主线程物化（Materialize）。

---

## 菜单项类型

| 类 | 说明 | 关键参数 |
|---|---|---|
| `MenuItem` | 普通可点击菜单项 | `text`, `id=None`, `enabled=True`, `accelerator=None`, `on_activate=None` |
| `CheckMenuItem` | 带勾选框的菜单项 | 继承 `MenuItem`，增加 `checked=False` 与 `set_checked(bool)` |
| `Submenu` | 子菜单 / 顶级菜单栏分类 | `text`, `items=[]`, `id=None`, `enabled=True` |
| `PredefinedMenuItem` | 系统原生动作（复制/粘贴/分隔线/关于等） | 工厂方法如 `.separator()`, `.copy()`, `.paste()`, `.about(name=..., version=...)` |

> **说明**：`PredefinedMenuItem` 由操作系统原生接管执行，**不会**触发 Python 侧激活事件。若希望在 macOS 下点击退出时走 `App` 的优雅关闭，请使用绑定了 `app.exit()` 的普通 `MenuItem`（`App.run()` 在 macOS 默认安装的菜单栏中已为你处理好这一点）。

---

## 创建、动态修改与事件回调

### 双写模型与多线程安全

- **属性修改**：`item.set_text(...)`、`item.set_enabled(...)`、`item.set_accelerator(...)`、`check_item.set_checked(...)` 均可在任意线程安全调用，返回 `Task[None]`。
- **结构修改**：`menu.append/insert/remove` 与 `submenu.append/insert/remove` 自动在主线程串行执行，避免多线程操作造成数据顺序与原生菜单不一致。
- **快照与复制**：`menu.items` 返回顶级条目的只读 `tuple` 快照；如需基于已有条目克隆并保留原 `id` 与回调，请使用 `item.copy(text="新名称")`（不要使用 `dataclasses.replace`）。

### 菜单事件示例（Windows / macOS）

```python
import sys
from lumiview import (
    App,
    AppEvent,
    CheckMenuItem,
    Menu,
    MenuItem,
    PredefinedMenuItem,
    Submenu,
    Window,
    WindowOptions,
)

app = App(name="MenuDemo")

mute_item = CheckMenuItem(text="静音", accelerator="CmdOrCtrl+M", id="mute")


@mute_item.on_activate
def on_mute(event: AppEvent.MenuItemActivatedEvent):
    print("当前静音状态:", mute_item.checked)


async def on_open(event: AppEvent.MenuItemActivatedEvent):
    print("打开文件触发:", event.id)


file_menu = Submenu(
    text="文件",
    items=[
        MenuItem(text="打开…", accelerator="CmdOrCtrl+O", id="open", on_activate=on_open),
        mute_item,
        PredefinedMenuItem.separator(),
        MenuItem(text="退出", id="quit", on_activate=lambda _: app.exit()),
    ],
)


async def main():
    win = await Window.create(WindowOptions(title="Menu Demo"))

    # 也可监听全局菜单激活频道（在条目自身的 on_activate 之后触发）
    @app.on(AppEvent.MenuItemActivatedEvent)
    def on_any(event: AppEvent.MenuItemActivatedEvent):
        print(f"全局菜单事件: id={event.id!r}")

    menu = await Menu.create(items=[file_menu])

    if sys.platform == "win32":
        await menu.attach_to_window(win)   # Windows：挂载到指定窗口菜单栏
    elif sys.platform == "darwin":
        await menu.install_nsapp()         # macOS：替换应用顶部全局菜单栏


app.run(main)
```

> **平台提示**：Windows 下菜单栏中的快捷键文字仅作展示，`tao` 消息循环默认不自动转发快捷键触发，通常建议在页面 JS 中监听键盘快捷键并通过 Bridge 触发对应逻辑。

---

## 系统托盘与 Close-to-Tray 实践

通过将 `exit_on_last_window=False`、`WindowEvent.CloseRequestedEvent` 与 `App.hide()` 结合，即可实现跨平台的最小化到托盘模式：

```python
from lumiview import (
    App,
    AppEvent,
    ElementState,
    Menu,
    MenuItem,
    MouseButton,
    PredefinedMenuItem,
    TrayIcon,
    TrayIconOptions,
    Window,
    WindowEvent,
    WindowOptions,
)

app = App(name="TrayDemo", exit_on_last_window=False)


def make_icon() -> tuple[bytes, int, int]:
    # 生成 32x32 纯蓝色 RGBA 图标（也可直接传文件路径或 PIL.Image.Image）
    return bytes([66, 133, 244, 255] * (32 * 32)), 32, 32


async def main():
    win = await Window.create(WindowOptions(title="Tray Demo", html="<h1>点击关闭隐藏到托盘</h1>"))

    async def restore():
        await win.show()
        await win.focus()

    # 点击关闭按钮时不销毁窗口，而是隐藏整个应用
    @win.on(WindowEvent.CloseRequestedEvent)
    async def on_close(event):
        event.prevent()
        await app.hide()

    # macOS 专属：点击 Dock 图标时重新显示隐藏的窗口
    @app.on(AppEvent.ReopenEvent)
    async def on_reopen(event):
        if not event.has_visible_windows:
            await restore()

    # 左键释放托盘图标时切换窗口显隐
    @app.on(AppEvent.TrayIconClickEvent)
    async def on_tray_click(event):
        if event.button == MouseButton.Left and event.button_state == ElementState.Released:
            await win.toggle_visibility()

    tray_menu = await Menu.create(
        items=[
            MenuItem(text="显示窗口", on_activate=lambda _: restore()),
            PredefinedMenuItem.separator(),
            MenuItem(text="完全退出", on_activate=lambda _: app.exit()),
        ]
    )

    tray = await TrayIcon.create(
        TrayIconOptions(
            icon=make_icon(),
            tooltip="LumiView 托盘示例",
            menu=tray_menu,
            menu_on_left_click=False,   # 左键切换窗口，右键弹出菜单
            menu_on_right_click=True,
        )
    )


app.run(main)
```

### macOS 纯菜单栏（Agent）应用

如果你希望应用完全不显示在 macOS Dock 栏和 `Cmd+Tab` 切换器中，只需设置 `ActivationPolicy.Accessory`：

```python
from lumiview import ActivationPolicy, App

app = App(
    name="MenuBarAgent",
    exit_on_last_window=False,
    activation_policy=ActivationPolicy.Accessory,  # 仅 macOS 允许传入
)
```

运行期还可通过 `await app.set_dock_visibility(True/False)` 动态切换 Dock 图标显示。

> **Linux 托盘限制**：受底层系统托盘协议限制，Linux 上不支持 `tooltip`，且托盘菜单在创建后无法动态整棵替换（建议创建时就装配好完整菜单）。
