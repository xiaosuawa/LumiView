# 应用生命周期与事件系统

## `App` 状态机与优雅关闭

`App` 只有一个全局单例（通过 `App.get()` 获取），生命周期严格单调推进：

```text
CREATED ──(app.run)──▶ RUNNING ──(原生循环退出)──▶ STOPPED
```

可以通过 `app.state`、`app.is_running`、`app.is_stopped` 查询当前阶段。

### 两阶段关闭流程

调用 `app.exit(code=0)`、最后一个窗口关闭（`exit_on_last_window=True`）、按下 `Ctrl+C` 或 macOS 点击 `Cmd+Q` 时，关闭过程分为两个阶段：

1. **协商阶段（`AppEvent.CloseRequestedEvent`，可取消）**
   - 在 `asyncio` 线程运行，此时 `App` 依然处于 `RUNNING` 状态，**所有窗口、WebView、托盘和菜单都完全存活**。
   - 你可以在处理器中调用 `await win.eval_js(...)` 保存未保存的数据，甚至创建临时窗口。
   - 若调用 `event.prevent()`，本次退出被取消，应用恢复正常运作，之后的 `app.exit()` 会重新发起新一轮协商。
   - *注*：关闭协商期间再次按下 `Ctrl+C` 会触发强制退出；若是进程被操作系统直接销毁，则直接进入第二阶段。

2. **清理与完结阶段（`AppEvent.ClosedEvent`，不可逆）**
   - 原生事件循环退出，`app.state` 原子切换为 `STOPPED`，挂起中的 `call_on_main` 请求全部以 `AppClosedError` 结算。
   - 按顺序释放原生资源：先关闭所有窗口（并触发各自的 `WindowEvent.ClosedEvent`），再释放托盘图标与菜单。
   - 派发 `AppEvent.ClosedEvent(exit_code=...)`（此时不应再发起新原生调用）。
   - 等待关闭处理器完成后，取消剩余异步任务（确保协程的 `finally` 块正常执行）、关闭异步生成器并关闭线程池。

```python
from lumiview import App, AppEvent

app = App(name="LifecycleDemo")


@app.on(AppEvent.ReadyEvent)
async def on_ready(event: AppEvent.ReadyEvent):
    # 所有 ReadyEvent 处理器执行完毕后，才会启动 app.run(main) 中的 main
    print("App 已就绪")


@app.on(AppEvent.CloseRequestedEvent)
async def on_close_requested(event: AppEvent.CloseRequestedEvent):
    # 此时窗口和 API 仍可用
    for win in app.windows:
        dirty = await win.eval_js("window.__hasUnsavedChanges")
        if dirty == "true":
            event.prevent()  # 取消关闭
            return


@app.on(AppEvent.ClosedEvent)
async def on_closed(event: AppEvent.ClosedEvent):
    print(f"应用已完全退出，退出码: {event.exit_code}")
```

> **关于 `entry` 异常**：`app.run(main)` 中的 `main` 若抛出未捕获异常，框架会记录错误日志并自动调用 `app.exit(1)`，最终 `app.run()` 返回 `1`。

---

## 事件订阅、过滤与取消

`app.on(...)` 和 `win.on(...)` 同时支持**装饰器写法**和**直接传参写法**，并返回一个可随时取消的 `Subscription` 对象：

```python
from lumiview import WindowEvent

# 1. 装饰器形式 + where= 同步过滤谓词
@win.on(WindowEvent.JsEvent, where=lambda e: e.event == "user.login")
async def on_login(event: WindowEvent.JsEvent):
    print("用户登录:", event.payload)


# 2. 命令式注册 + 保存 Subscription 以便后续取消
sub = win.on(WindowEvent.TitleChangedEvent, lambda e: print("新标题:", e.title))
# 不再监听时：
sub.cancel()  # 幂等操作，可重复调用
```

- `handler` 可以是 `def`（在线程池执行）或 `async def`（在 asyncio 线程执行）。
- `where=` 在派发时同步内联执行，**必须是普通同步函数**。若 `where` 自身抛出异常，会被记录日志并视为不匹配。

---

## 一次性等待：`wait_for()` 与 `wait_loaded()`

当你只想在协程里等待“下一次某事件发生”时，无需手动拼装 `asyncio.Event`：

```python
# 等待窗口加载完成（推荐：Window.create() 内部已预注册，不存在竞态）
await win.wait_loaded(timeout=10)

# 注册一次性事件等待器（务必在触发该事件的操作之前注册）
waiter = win.wait_for(
    WindowEvent.TitleChangedEvent,
    where=lambda e: "完成" in e.title,
    timeout=5.0,
)
await win.eval_js("document.title = '任务完成'")
event = await waiter
print(event.title)
```

- 如果窗口或应用在事件到达前关闭，未完成的 `wait_for` 会立即以 `WindowClosedError` 或 `AppClosedError` 失败，绝不会无限期挂起。
- 超时后抛出 `TimeoutError`。

---

## 事件类体系与可阻止事件

所有事件继承自 `Event`；只有真正支持取消默认行为的事件才继承 `WindowPreventableEvent` 或 `AppPreventableEvent`（拥有 `.prevent()` 与 `.prevented`）：

### `AppEvent` 一览

| 事件类 | 是否可阻止 | 关键字段与说明 |
|---|---|---|
| `AppEvent.ReadyEvent` | ❌ | 应用就绪，在 `entry` 之前执行并等待完成 |
| `AppEvent.CloseRequestedEvent` | ✅ | 退出协商，`exit_code: int` |
| `AppEvent.ClosedEvent` | ❌ | 彻底关闭后触发，`exit_code: int` |
| `AppEvent.ReopenEvent` | ❌ | macOS 点击 Dock 图标时触发，`has_visible_windows: bool` |
| `AppEvent.OpenedEvent` | ❌ | 通过自定义 URL Scheme / 文件关联唤起应用，`urls: list[str]` |
| `AppEvent.MenuItemActivatedEvent` | ❌ | 菜单项激活，`id: str`, `menu_item` |
| `AppEvent.TrayIconClickEvent` 等 | ❌ | 托盘点击/双击/移入/移动/移出，含 `id`, `position`, `rect`, `tray` |
| `AppEvent.Device*Event` | ❌ | 全局设备事件（连接/断开/鼠标/滚轮/按键/文本） |

### `WindowEvent` 一览

| 分类 | 事件类 | 是否可阻止 | 关键字段与说明 |
|---|---|---|---|
| **页面** | `PageLoadStartedEvent` / `PageLoadFinishedEvent` | ❌ | `url: str` |
| | `TitleChangedEvent` | ❌ | `title: str` |
| **拦截** | `NavigationRequestedEvent` | ✅ | `url: str`，`prevent()` 阻止页面跳转 |
| | `NewWindowRequestedEvent` | ✅ | `url: str`（默认拒绝内嵌新建并调系统浏览器打开；`prevent()` 完全拦截；`open_in(url)` 修改外跳地址） |
| | `DownloadStartedEvent` | ✅ | `url: str`, `suggested_path: str`；`prevent()` 取消或 `save_to(path)` 重定向保存路径 |
| | `DownloadCompletedEvent` | ❌ | `url: str`, `saved_path: str \| None`, `success: bool` |
| **窗口** | `CloseRequestedEvent` | ✅ | `prevent()` 取消本次关闭，否则按 `close_behavior` 执行 |
| | `ClosedEvent` | ❌ | 窗口与 WebView 已销毁（触发一次） |
| | `ResizedEvent` / `MovedEvent` | ❌ | 物理像素 `width`, `height` / `x`, `y` |
| | `FocusedEvent` / `UnfocusedEvent` | ❌ | 窗口获得/失去焦点 |
| | `ScaleFactorChangedEvent` | ❌ | `scale_factor: float` |
| | `ThemeChangedEvent` | ❌ | `theme: Theme`（`Light` / `Dark`） |
| | `StartedEvent` / `SuspendedEvent` / `ResumedEvent` / `StoppedEvent` / `DecorationsClickEvent` | ❌ | 窗口状态与装饰区双击生命周期 |
| **拖拽与输入** | `DragEvent` | ❌ | 文件拖放，`kind: DragDropEvent`, `paths`, `position`（**需开启 `WindowOptions(drag_drop=True)`**） |
| | `ReceivedImeTextEvent` | ❌ | 输入法组合文本 `text: str` |
| | `TouchpadPressureEvent` / `AxisMotionEvent` / `TouchEvent` | ❌ | 触控板压感、摇杆轴与触屏事件 |
| **IPC** | `JsEvent` | ❌ | 页面 `__LUMIVIEW__.emit()` 发出，`event: str`, `payload` |
| | `WebMessageReceivedEvent` | ❌ | 所有来自 `window.ipc.postMessage` 的原始消息字符串 `message: str` |

### 预置导航策略：`utils.navigation_policy`

如果希望快速限制 WebView 只允许访问指定域名（`*` 通配符，`deny` 优先于 `allow`）：

```python
from lumiview import WindowEvent, utils

win.on(
    WindowEvent.NavigationRequestedEvent,
    utils.navigation_policy(
        allow=("lumiview://*", "https://example.com/*"),
        deny=("https://example.com/admin/*",),
    ),
)
```

> **提示**：对于 `PageLoadStartedEvent` 等窗口刚创建就可能触发的早期事件，可通过 `WindowOptions(prepare=...)` 钩子在原生窗口实例化前完成订阅。
