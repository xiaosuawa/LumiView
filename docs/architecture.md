# 架构

## 分层

```
Rust 层                       Python 层
──────────────────────       ──────────────────────────────────
tao（窗口/事件循环）           lumiview.app    — App 单例、2+N 线程编排
  │                            lumiview.window — Window / WindowOptions
  ▼                            lumiview.bridge — Bridge / BridgeError（IPC）
wryview（WebView 绑定）        lumiview.scope  — Scope / Plugin / 权限链
  │                            lumiview.task   — Task / run_async
  ▼                            lumiview.events — 事件类体系
lumiview._core（PyO3）         lumiview.utils  — match_pattern / navigation_policy
                              lumiview.serve  — lumiview:// 自定义协议
```

- Rust 层只做薄绑定：`TaoEventLoop` / `TaoWindow` 等对象是 `#[pyclass(unsendable)]`，方法即原生调用。
- 低层绑定入口是 `lumiview._core`；日常开发用顶层 `lumiview` API。
- 所有跨线程/延迟操作统一返回 `Task[T]`：`await`、`.result()`、`.on_done()` 三用一体。

## 2+N 线程模型

| 线程 | 职责 |
|---|---|
| **主线程** | tao 事件循环 + 所有原生窗口/WebView 操作 |
| **asyncio 线程** | 运行用户协程（`app.run(entry)` 的 entry）与事件 handler |
| **线程池** | 同步 `task()` 调用、同步事件 handler（大小由 `App(max_workers=N)` 配置） |

关键推论：

- **事件 handler 从不运行在主线程**——它们跑在 asyncio 线程（同步 handler 经由线程池）。
- 主线程 GUI 库操作必须显式调度：`app.call_on_main(...)`。

## 事件流

```
tao 事件
  → Rust build_event() 构造 TaoEvent 子类（ResizedEvent 等）
  → App._on_tao_event（主线程）按 window_id 路由
  → Window._on_tao_event → 构造事件类实例（WindowEvent.ResizedEvent 等）
  → Window._emit(event)：按 type(event) 找到 handler，投递到 asyncio 线程
  → handler(event) 收到事件对象（event.window 已填充）
```

可阻止事件（`CloseRequestedEvent` / `NavigationRequestedEvent` / `NewWindowRequestedEvent` / `DownloadStartedEvent`）走 `_dispatch_preventable`：先派发并**等待** handler 完成，再检查 `event.prevented` 决定是否执行默认行为（如关闭窗口、放行导航、允许下载）。

## 事件类体系

```text
Event                     # 所有事件的公共祖先
├── WindowBaseEvent       # 窗口事件基类：数据 + prevent()/prevented
│     window: Window | None
└── AppBaseEvent          # 应用事件基类（ReadyEvent / AppCloseEvent）

WindowEvent               # 纯命名空间容器（非基类）
├── WindowEvent.TitleChangedEvent(WindowBaseEvent)
├── WindowEvent.CloseRequestedEvent(WindowBaseEvent) # 可 prevent()
├── WindowEvent.NavigationRequestedEvent             # 可 prevent()
├── WindowEvent.DownloadStartedEvent                 # 可 save_to(path) / prevent()
└── ...
```

命名空间访问与 isinstance 检查同时成立：

```python
from lumiview.events import WindowEvent, WindowBaseEvent

e = WindowEvent.TitleChangedEvent(title="x")
assert isinstance(e, WindowBaseEvent)
assert e is not None and e.title == "x"
```

## 主线程调度机制

| API | 说明 |
|---|---|
| `app.call_on_main(fn, *args)` | 把 *fn* 排到主线程执行，返回 `Task[T]`；主线程上直接执行 |
| `@main_thread` | 装饰器版：同步方法变成返回 `Task[R]` 并在主线程跑方法体 |
| `Task` | `concurrent.futures.Future` 子类；`await` / `.result()` / `.on_done()` |
| `run_async(fn)` | 轻量派发（无 Task 开销）：async 直接 await，sync 走线程池 |

```python
from lumiview import App
from lumiview.task import run_async

app = App.get()

# 异步代码：直接 await
result = await app.call_on_main(lambda: window_op())

# 同步代码：.result() 阻塞
result = app.call_on_main(lambda: window_op()).result()

# 混合回调：async 直接跑、sync 去线程池
await run_async(mixed_callback)
```

> 经验：任何「从别的线程操作原生窗口」的崩溃（尤其 macOS）基本都是没走 `call_on_main`。典型案例：TimeFlow 用 pystray 时，状态栏菜单回调线程直接操作 `NSWindow` 崩溃——改为主线程调度后稳定。见 [integrations.md](integrations.md)。

## 不可跨线程对象（unsendable）

| 对象 | 跨线程 | 说明 |
|---|---|---|
| `TaoEventLoop` | ❌ | tao `!Send`（Rust 侧标记） |
| `TaoEventLoopProxy` | ✅ | 跨线程唤醒通道（`send_event`） |
| `TaoWindow` | ❌ | 主线程操作（含 Windows 透明 surface 重绘） |
| `WebView`（wryview） | ❌ | 主线程 |
| `Window`（Python 层） | ✅ 方法走 `@main_thread` | 唯一的线程安全通道 |

`Window` 把不可跨线程的原生对象直接存在实例上（`win._window` / `win._webview`），所有访问经 `call_on_main` 派发到主线程——外部永远不直接触碰原生对象。

## 设计原则

1. **跨线程/延迟操作返回 `Task`** —— 类型和行为可预测，不做上下文相关的自动解包。
2. **事件 handler 不跑主线程** —— 主线程只属于 tao 循环与原生操作，事件处理在 asyncio 线程。
3. **配置即数据** —— `WindowOptions` 是（可变的）dataclass：可 `replace`、可子类做模板（子类需重新应用 `@dataclass`）、可跨线程传递。
