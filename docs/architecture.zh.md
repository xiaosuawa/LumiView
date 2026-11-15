# 架构

LumiView 刻意做得很小：一个 Rust 扩展包住 tao（窗口/事件循环）、wry（WebView）、
muda（菜单）和 tray-icon，外加一层 Python，把它变成 async 优先、线程安全的 API。

```
你的代码
   │
   ▼
lumiview.*            App、Window、Bridge、Menu、Tray、Serve、Task   （Python）
   │
   ▼
lumiview._core        PyO3 绑定：TaoEventLoop、TaoWindow……            （Rust）
   │
   ▼
tao  wry  muda  tray-icon  window-vibrancy                            （Rust crates）
   │
   ▼
系统窗口 + 系统 WebView
```

页面侧是独立的 TypeScript 客户端（`js/`，注入为 `window.__LUMIVIEW__`），
见 [js-client.zh.md](js-client.zh.md)。

## 线程

| 线程 | 跑什么 |
|---|---|
| **主线程** | tao 事件循环，以及所有原生窗口 / WebView 调用 |
| **asyncio 线程** | 你的 `async` 代码：`entry`、`async` handler、`async` 命令、ASGI 应用 |
| **线程池** | 同步 `task()`、同步 handler、同步命令、WSGI 应用 |

线程池大小由 `App(max_workers=N)` 决定（默认 6）。asyncio 事件循环有自己的线程，
由 `app.run()` 创建。

由此得到的规则：

- 原生对象（`TaoWindow`、`WebView`）是 **unsendable** 的：跨线程操作会崩。
  `Window` 的每个调用都经 `app.call_on_main` 切回主线程。
- handler 永远不在 GUI 线程运行，所以可以自由 `await`，但不能直接调原生 API。
- GUI 线程不能长时间阻塞在 `Task` 上——见下文。

## Task

所有跨线程 / 延迟操作都返回 `Task[T]`，它是 `concurrent.futures.Future` 的子类：

```python
result = await handle                # asyncio 线程——首选
result = handle.result()             # 阻塞，非 asyncio 线程
handle.on_done(callback)             # 不阻塞
handle.on_exception(callback)
```

`Task.result()` 的行为取决于调用线程：

| 调用位置 | 行为 |
|---|---|
| asyncio 线程 | 抛 `TaskDeadlockError`（否则会卡死事件循环） |
| GUI 线程 | 边等边泵主线程命令队列——窗口会冻结 |
| 其它线程 | 正常阻塞 |

`task(fn, *args)` 把函数调度出去并包成 `Task`：`async` 进 asyncio 线程，普通函数进线程池。
`app.call_on_main(fn, ...)` 是通往 GUI 线程的唯一桥——在主线程上直接执行，其它线程排队，
由 tao 回调循环抽取执行。

失败的 `Task` 如果异常一直没人取，会在被垃圾回收时记一条 error 日志；不要静默丢失败。

## 事件

```
tao 事件
  → lumiview._core 构造 TaoEvent 子类（ResizedEvent……）
  → App._on_tao_event（主线程）按窗口 id 路由
  → Window._emit(event)：按类型找 handler，执行 where 过滤
  → handler：async 进 asyncio 线程，同步进线程池
```

- handler 用 `win.on(EventClass, where=...)` 注册；`where` 是同步的
  `(event) -> bool` 过滤函数，参数类型由具体事件类绑定。过滤函数抛异常时按
  「不匹配」处理并记日志，不会中断派发。
- `win.on(...)` / `app.on(...)` 返回 `Subscription`；`.cancel()` 注销 handler
  （幂等）。已经在派发中的事件仍可能再调用一次。
- 派发前会填好 `event.window`。
- `_emit` 返回一个在所有 handler 完成后才完成的 `Task`（没人监听时为 `None`）。
- **可阻止事件**（`CloseRequested`、`NavigationRequested`、`NewWindowRequested`、
  `DownloadStarted`）来自同步的 WebView 回调。LumiView 派发后会阻塞回调直到 handler
  全部结束，再检查 `event.prevented`——所以这些事件的 handler 不能阻塞 GUI 线程。
- `wait_for(...)` 是 one-shot：注册目标 handler 加一个内部关闭 handler，命中后 resolve
  并移除两者。`Window.wait_for` 把 `ClosedEvent` 视为「太迟了」（`WindowClosedError`），
  `App.wait_for` 用 `AppCloseEvent`（`AppClosedError`）。`wait_loaded()` 是同一机制，
  只是在创建时预注册，因此不会和页面加载抢跑。

## 应用生命周期

```
CREATED ──run()──▶ STARTING ──▶ RUNNING ──exit()──▶ STOPPING ──▶ STOPPED
```

- `run(entry)` 只能在主线程调用一次，阻塞直到退出。
- 应用就绪后先派发 `AppEvent.ReadyEvent`，随后启动 `entry`。两者之一抛异常都会以
  退出码 1 结束（首次退出请求生效）。
- `exit(code)` 记录请求（首次请求生效），立即停止接收跨线程工作——`call_on_main`、
  `wait_for`、bridge invoke、serve 请求都会快速失败（`AppClosedError` / 错误响应）——
  并唤醒事件循环。清理集中在一处。
- `app.windows` / `app.get_window(id)` / `win.id` / `win.is_closed` 是加锁的普通读取；
  `app.async_loop` 在 `run()` 之前和关停期间为 `None`，第三方线程可先检查再调度。
- 退出顺序：停止接收新工作 → 关闭所有窗口（派发 `ClosedEvent`）→ 释放托盘 →
  释放菜单 → 派发 `AppCloseEvent` → 取消未完成的 asyncio 任务 → 停事件循环 →
  失败未完成的主线程 handle → 关闭线程池。
- 运行期异常（handler、命令、serve 回调、`call_on_main`）只记日志，不会崩掉应用；
  启动阶段（`entry`、Ready handler、`prepare`）的异常则让启动失败。

`Ctrl+C` 会把 `app.exit()` 投递到 asyncio 循环；直接在信号 handler 里调用 `exit()`
可能重入主线程已持有的锁。

## JS 桥

```
页面                                       Python
────                                       ──────
__LUMIVIEW__.invoke(cmd, payload)
  → window.ipc.postMessage(JSON)   ──▶  Bridge._on_message(raw)
                                          权限链 → bind_arguments
                                          在非 GUI 线程执行命令
  ◀── eval_js "dispatch({...})"           Bridge._respond(...)
promise resolve / reject
```

- `window.ipc.postMessage` 是 wry 的通道，每个 LumiView 窗口都有。
- Python → 页面走 `eval_js`，入口只有一个：`dispatch()`。
- `invoke` 先过权限链（`Scope` 树）再绑定参数。
- 命令不在 GUI 线程执行：`async def` 在 asyncio 线程，`def` 在线程池。
- `Bridge` 持有窗口生命周期内的命令树；`Window.bridge` 是只读 getter
  （`untrusted` 模式下为 `None`）。需要扩展命令时直接在其上注册。
- `untrusted=True` 两个方向都关掉：不注入客户端，也不解析收到的消息。

细节见 [plugins.zh.md](plugins.zh.md) 与 [js-client.zh.md](js-client.zh.md)。

## 模块

| 模块 | 职责 |
|---|---|
| `lumiview.app` | `App` 单例、状态机、`run`/`exit`、`call_on_main`、事件总线 |
| `lumiview.window` | `Window`、`WindowOptions`、`WebContext`，原生窗口 + WebView |
| `lumiview.events` | 事件类，以及 `WindowEvent` / `AppEvent` 命名空间 |
| `lumiview.task` | `Task`、`task()`、`run_async()`、死锁规则 |
| `lumiview.bridge` | `Bridge`、`BridgeError`、IPC 分发、注入的 JS 客户端 |
| `lumiview.scope` | `Scope` 树、权限、`Plugin`、`BridgeContext` / `InitContext` |
| `lumiview._binding` | payload → Python 签名绑定（严格模式） |
| `lumiview.menu` / `lumiview.tray` | 原生菜单与托盘（数据 wrapper，在 GUI 线程物化） |
| `lumiview.serve` | `lumiview://` 协议：`Static`、`Handler`、`WSGI`、`ASGI` |
| `lumiview.utils` | 公共辅助：模式匹配、导航策略 |
| `lumiview._utils` | 内部辅助（`Task` 胶水、`Subscription`、等待辅助、`main_thread`） |
| `lumiview.plugins` | 内置 `WindowControls` |
| `lumiview._core` | Rust 绑定（tao/wry/muda/tray-icon） |

## 设计原则

1. **只有一种 `Task`**——所有跨线程 / 延迟调用都返回 `Task[T]`，不做上下文相关的自动解包。
2. **不强制项目结构**——LumiView 提供窗口 + WebView 运行时，不提供脚手架、配置文件或前端约定。
3. **Pythonic，同步异步同源**——同一套 API 两种写法都能用，区别只在 `.result()` 与 `await`。
4. **边界处大声失败，运行期只记日志**——启动错误直接终止；运行期错误记录后继续跑。
