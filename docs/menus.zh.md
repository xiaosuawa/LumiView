# 菜单与托盘

菜单项是纯数据对象：你可以在任何地方（`App.run` 之前也行）构造它们，
等菜单挂到窗口、macOS 应用菜单或托盘图标上时，才在 GUI 线程物化成原生对象。

```python
from lumiview import AppEvent, CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu

mute = CheckMenuItem(text="Mute", accelerator="CmdOrCtrl+M", id="mute")


def on_open(event: AppEvent.MenuItemActivatedEvent) -> None:
    print("open", event.id)


file_menu = Submenu(
    text="File",
    items=[
        MenuItem(text="Open…", accelerator="CmdOrCtrl+O", id="open", on_activate=on_open),
        mute,
        PredefinedMenuItem.separator(),
        MenuItem(text="Quit", id="quit", on_activate=lambda _: app.exit()),
    ],
)

menu = await Menu.create(items=[file_menu])
```

- 条目 id 是字符串，激活时原样回传；不传 `id=` 会自动生成。
- `accelerator` 用 muda 语法：`Ctrl`、`Shift`、`Alt`、`Cmd`、`CmdOrCtrl`，
  例如 `"CmdOrCtrl+Shift+K"`。
- `PredefinedMenuItem` 覆盖系统条目（`separator()`、`copy()`、`cut()`、`paste()`、
  `undo()`、`quit()`、`about()`……）。它们执行系统行为，不会派发激活事件。
- handler 可以是同步或 `async`，都离开 GUI 线程运行。可以在构造时传
  `on_activate=fn`，也可以之后用装饰器 `@item.on_activate` 注册。

## 挂载

```python
# Windows：窗口菜单栏
await menu.attach_to_window(win)
await menu.remove_from_window(win)

# macOS：应用菜单栏
await menu.install_nsapp()
await menu.remove_from_nsapp()
```

`attach_to_window` 仅 Windows 可用，`install_nsapp` 仅 macOS 可用——其它平台调用会抛
`NotImplementedError`。`App.run()` 会在 macOS 上自动安装默认应用菜单
（Application / Edit / Window），自定义菜单直接替换它。Linux 没有窗口菜单栏。

激活时有两条通道，按顺序触发：

1. 条目自己的 `on_activate`（只有叶子条目）；
2. 全局 `AppEvent.MenuItemActivatedEvent`（给 `app.on(...)` 用），
   其中 `menu_item` 字段是对应的 wrapper。

## 运行期修改条目

状态存在 Python wrapper 里，物化之后会同步到原生条目（双写）：

```python
await item.set_text("Save as…")
await item.set_enabled(False)
await check_item.set_checked(True)
await item.set_accelerator("CmdOrCtrl+Shift+S")
```

以 wrapper 为准（比如 `check_item.checked`），不要依赖 `event.menu_item`——
它的类型是联合类型。

## 读取与复制条目

`Menu.items` 是只读快照（`tuple[Item, ...]`）。要基于现有条目派生变体，用
`MenuItem.copy(**changes)` / `Submenu.copy(**changes)`，不要用
`dataclasses.replace`：

```python
save_as = file_menu.items[0].copy(text="Save As…", id="save-as")
```

`copy()` 会保留 `id` 和已注册的 `on_activate` handler——这两个都是 `init=False`
字段，`dataclasses.replace` 会重新生成 id 并静默丢掉激活回调。传入未知字段名会抛
`TypeError`。

## 托盘图标

```python
from lumiview import Menu, MenuItem, PredefinedMenuItem, TrayIcon, TrayIconOptions

menu = await Menu.create(items=[MenuItem(text="Show", id="show"), PredefinedMenuItem.separator(), MenuItem(text="Quit", id="quit")])

tray = await TrayIcon.create(
    TrayIconOptions(
        icon=(rgba_bytes, 32, 32),      # 原始 RGBA、文件路径或 PIL 图片
        tooltip="My App",
        menu=menu,
        menu_on_left_click=False,
    )
)

await tray.set_tooltip("Busy")
await tray.set_visible(False)
await tray.close()                      # 或者直接丢掉 wrapper
```

`TrayIconOptions` 字段：`icon`、`id`、`tooltip`、`menu`、`menu_on_left_click`、
`menu_on_right_click`、`icon_as_template`（macOS 模板图像）。

## 托盘事件

```python
from lumiview import AppEvent, ElementState, MouseButton

@app.on(AppEvent.TrayIconClickEvent)
async def on_click(event):
    if event.button == MouseButton.Left and event.button_state == ElementState.Released:
        await win.toggle_visibility()
```

`TrayIconClickEvent` 带 `id`、`position`、`rect`、`button`、`button_state` 和 `tray`。
此外还有 `TrayIconDoubleClickEvent`（仅 Windows）、`TrayIconEnterEvent`、
`TrayIconMoveEvent`、`TrayIconLeaveEvent`，都以全局事件派发。

## 关闭到托盘

```python
app = App(name="TrayApp", exit_on_last_window=False)

@win.on(WindowEvent.CloseRequestedEvent)
async def on_close_requested(event):
    event.prevent()
    await app.hide()
```

配合 `exit_on_last_window=False`，窗口隐藏后应用继续运行；从托盘点击或菜单项恢复。
macOS 上 Dock 点击会触发 `AppEvent.ReopenEvent`。

## 平台差异

- **Windows**：菜单 accelerator 只显示，不生效——WebView2 内容获得键盘焦点时，
  消息循环收不到按键。需要可用的快捷键时，走 JS `keydown` + IPC。
- **macOS**：应用菜单栏在没有任何窗口时也存在；`App.hide()` 会把窗口收进 Dock。
- **Linux**：没有窗口菜单栏；托盘不支持 tooltip；托盘菜单创建后不能替换。
- 菜单和托盘 wrapper 由应用持有；`TrayIcon` 被回收时图标会被移除。
