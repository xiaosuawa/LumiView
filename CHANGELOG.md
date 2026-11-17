## 0.2.0rc1 Release Notes

> ⚠️ **Alpha Pre-release**: `0.2.0rc1` introduces architectural refactors, lifecycle semantic changes, and breaking API updates. Please review the Breaking Changes & Migration Guide below before upgrading.

### ✨ Highlights

- **Two-phase graceful shutdown**: Replaced `AppCloseEvent` with preventable `AppEvent.CloseRequestedEvent` (runs while windows and native resources are still alive) and irreversible `AppEvent.ClosedEvent`.
- **TypeScript JS client (`window.__LUMIVIEW__`)**: Rebuilt the page-side bridge client in `js/` with locked read-only core methods, `EventTarget`-backed event listening, `BridgeError` class support, and page-to-Python `emit()` (`WindowEvent.JsEvent`).
- **Free-threaded Python support**: Upgraded to PyO3 `0.30` with `#[pymodule(gil_used = false)]` and added `cp314-cp314t` and `cp315-abi3.abi3t` (PEP 803) release wheel targets.
- **Event filtering & race-free waiters**: Added `Subscription`, `where=` predicates, `wait_for()`, and pre-registered `win.wait_loaded()`.
- **Full test & CI suite**: Added pure-Python unit tests, 19 end-to-end real-WebView scenario tests across Windows/macOS/Linux, and Node tests for the JS client.

---

### 💥 Breaking Changes & Migration

#### 1. JS Client Surface & Plugin Namespace
- Renamed global `window.lumiview` to `window.__LUMIVIEW__` (defined as non-enumerable, non-writable, non-configurable with read-only core methods).
- Unified `_dispatchResponse` / `_dispatchEvent` into `window.__LUMIVIEW__.dispatch(message)`.
- Moved `WindowControls` JS API from `window.lumiview.window.*` to `window.__LUMIVIEW__.plugins.<name>.*` (default: `window.__LUMIVIEW__.plugins.window.*`).

#### 2. App Lifecycle & States
- Simplified `AppState` to `CREATED`, `RUNNING`, and `STOPPED` (removed `STARTING` and `STOPPING`). Added `app.is_running`, `app.is_stopped`, and `app.async_loop`.
- Removed `AppEvent.AppCloseEvent`; use `AppEvent.CloseRequestedEvent` (cancellable via `event.prevent()`) and `AppEvent.ClosedEvent(exit_code=...)` (post-teardown).
- `AppClosedError()` no longer accepts `app_name`.
- Unhandled exceptions in `app.run(entry)` now exit with code `1` (`self.exit(1)`).

#### 3. Preventable Events & Removed Raw Input/Frame Events
- Split `WindowPreventableEvent` and `AppPreventableEvent` out from base events; non-preventable events no longer expose `prevent()` or `prevented`.
- Removed high-frequency raw input and per-frame loop events from `_core` and `AppEvent` to eliminate unnecessary GIL acquisitions:
  - `MouseInputEvent`, `CursorMovedEvent`, `MouseWheelEvent`, `KeyboardInputEvent`, `ModifiersChangedEvent`, `CursorEnteredEvent`, `CursorLeftEvent`
  - `AppEvent.NewEventsEvent`, `AppEvent.MainEventsClearedEvent`, `AppEvent.RedrawEventsClearedEvent`
  - `_core` types `ModifiersState`, `KeyLocation`, `StartCause`

#### 4. `Window` API Renames & Semantics
- `set_size(w, h)` → `set_inner_size(w, h)`
- `minimize(flag=True)` → `set_minimized(flag)` (consolidated and consistently syncs WebView visibility)
- `set_maximize(flag=True)` → `set_maximized(flag=True)`
- `set_enable(enabled)` → `set_enabled(enabled)`
- `focus(flag=True)` / `set_focused()` → `focus()`
- `set_background_color(r, g, b, a=255)` → `set_background_color((r, g, b, a))`
- `win._id` → public `win.id` (also added `win.is_closed` and `win.bridge`)
- Platform-specific `Window` methods now return a failed `Task` (`NotImplementedError`) on unsupported platforms instead of raising `AttributeError`.
- `win.emit()` in `untrusted=True` mode now returns a failed `Task` (`RuntimeError`) instead of resolving with `None`.

#### 5. `WindowOptions(bridge=None)` & `WSGI`
- When `untrusted=False` and `bridge=None`, `Window.create()` now attaches a default `Bridge()` and runs plugin lifecycle hooks (rejecting unknown commands).
- `WSGI(..., max_workers=...)` is deprecated (`DeprecationWarning`) and ignored; WSGI requests now run on `App`'s shared thread pool (`App(max_workers=...)`).

---

### 🚀 Added

- **TypeScript JS client (`js/`)**: Built with `esbuild` + `tsc`, generating `python/lumiview/_bridge_client.py` and typed ESM/CJS facades (`js/dist/`). Added `window.__LUMIVIEW__.emit()` → `WindowEvent.JsEvent`, `BridgeError` class, `v`/`build` metadata, and `EventTarget`-based `addEventListener`/`removeEventListener`.
- **Event ergonomics**: `where=` predicate filtering, imperative `on(event, handler)` support, cancellable `Subscription`, `App.wait_for()`, `Window.wait_for()`, `Window.wait_loaded()`, and `WindowEvent.ClosedEvent`.
- **Concurrency & introspection**: `Task.with_timeout()`, `Task.on_exception()`, `contextvars` propagation in `task()` / `run_async()`, `App.windows`, `App.get_window()`, `App.is_async_thread()`, `App.monitors()`, and `App.primary_monitor()`.
- **Menu & packaging**: `Menu.items` read-only snapshot, `MenuItem.copy()` / `Submenu.copy()`, PEP 561 `py.typed`, top-level exports for `DragDropEvent`, `WindowHandleKind`, `Subscription`, `WindowPreventableEvent`, and `AppPreventableEvent`.
- **CI & Verification**: Multi-ABI wheel matrix (`cp310-abi3`, `cp314-cp314t`, `cp315-abi3.abi3t`), cross-platform e2e & unit test workflow (`.github/workflows/test.yml`), and artifact verification scripts (`.github/scripts/`).

---

### 🔧 Changed & Fixed

- **GIL pre-filtering**: Added `is_python_event()` in Rust before `Python::attach` so ignored `tao` events never acquire the GIL.
- **Shutdown & concurrency**: Awaited `ReadyEvent` handlers before starting `entry`; added `_finalize_loop()` to cancel and await remaining asyncio tasks (running `finally` blocks) and shutdown asyncgens before stopping the loop; double `Ctrl+C` forces exit; macOS default `Quit` menu item now triggers `App.get().exit()`; added `App._spawn()` and locks (`_pending_lock`, `_handlers_lock`, `_windows_lock`) to eliminate shutdown races.
- **Window reliability**: `eval_js` / `emit` watch `WindowEvent.ClosedEvent` to fail cleanly with `WindowClosedError` if the window closes mid-flight; failed `Window.create()` rolls back via `_teardown_failed_create()` without triggering `exit_on_last_window`.
- **Bridge & plugins**: Cached command `signature` and `type_hints` on `Command`; fixed `strict=True` bypassing zero-parameter or `BridgeContext`-only commands; updated `WindowControls` to track per-window state via `WeakKeyDictionary`, guard script injection with `Symbol.for`, support custom `name=` mounts, and use `async def` handlers.
- **Task GC logging**: Fixed `Task.__del__` calling `self.exception()` (which cleared the unhandled flag) and fixed suppressing `asyncio.CancelledError` from error logs; added race-safe `Task._settle()`.
- **Menu & Serve**: Serialized `Submenu.append/insert/remove` on `@main_thread`; atomic `_inner` read in `MenuItem._native_call`; `WSGI` now uses `io.BytesIO`, unquotes `PATH_INFO`, and shares `App._threadpool`; `WSGI`/`ASGI`/`Handler` return `503` when shutting down; `Static` uses `email.utils.formatdate`.
- **Documentation**: Reorganized `docs/` into eight task-oriented guides (architecture/concurrency, lifecycle/events, windows/appearance, bridge/client, plugins/permissions, serve, menus/tray), each in English `*.md` and Chinese `*.zh.md`, with a new documentation index and updated README links.
- **Dependencies**: Updated to `wryview~=0.5.5`, `cattrs~=26.1`, `maturin>=1.16.0`, and `pyo3 0.30`.

## 0.2.0rc1 发行版说明

> ⚠️ **Alpha 预发布版本**：`0.2.0rc1` 包含多项架构重构、生命周期语义调整以及 Breaking Changes，升级前请仔细阅读下方「破坏性变更与迁移指南」。

### ✨ 亮点概览

- **两阶段优雅关闭**：新增可阻止的 `AppEvent.CloseRequestedEvent` 与不可逆的 `AppEvent.ClosedEvent`，清理逻辑执行期间窗口与原生资源依然存活，支持 `event.prevent()` 取消退出。
- **独立 TypeScript JS 客户端（`window.__LUMIVIEW__`）**：页面侧脚本重构为 `js/` 下的 TypeScript 工程，核心 API 只读锁定，支持原生 `EventTarget` 事件监听、结构化 `BridgeError` 与页面向 Python 发送的 `emit()` 事件（`WindowEvent.JsEvent`）。
- **Free-threading（无 GIL）支持**：升级至 PyO3 `0.30` 并启用 `gil_used = false`，新增 `cp314-cp314t` 与 `cp315-abi3.abi3t`（PEP 803）wheel 构建矩阵。
- **事件等待原语与竞态修复**：新增 `Subscription`、`where=` 过滤、`wait_for()` 以及无竞态的 `win.wait_loaded()`。
- **完整测试体系**：新增纯 Python 单元测试、19 个真实 WebView 跨平台端到端场景测试与 Node 侧 JS 客户端测试。

---

### 💥 破坏性变更与迁移指南（Breaking Changes）

#### 1. JS 全局对象与插件挂载路径变更
- 全局对象从 `window.lumiview` 更名为 `window.__LUMIVIEW__`，且通过 `Object.defineProperty` 设为不可枚举、不可覆写。
- 原内部响应/事件派发方法 `_dispatchResponse` / `_dispatchEvent` 合并为 `window.__LUMIVIEW__.dispatch(message)`。
- `WindowControls` 插件的 JS API 从 `window.lumiview.window.*` 迁移至 `window.__LUMIVIEW__.plugins.<name>.*`（默认为 `window.__LUMIVIEW__.plugins.window.*`）。

```js
// 0.1.2
await window.lumiview.invoke("greet", { name: "LumiView" });
window.lumiview.window.minimize();

// 0.2.0rc1
await window.__LUMIVIEW__.invoke("greet", { name: "LumiView" });
window.__LUMIVIEW__.plugins.window.minimize();
```

#### 2. App 状态机与关闭事件调整
- `AppState` 精简为 `CREATED`、`RUNNING`、`STOPPED`（移除 `STARTING`、`STOPPING`），新增 `app.is_running`、`app.is_stopped`、`app.async_loop`。
- 移除 `AppEvent.AppCloseEvent`，替换为两阶段事件：
  - `AppEvent.CloseRequestedEvent`：退出协商阶段触发，此时窗口与事件循环仍存活，可调用 `event.prevent()` 取消退出。
  - `AppEvent.ClosedEvent(exit_code=...)`：原生循环退出且资源释放后触发，不可阻止。
- `AppClosedError()` 不再接受 `app_name` 参数。
- `entry` 入口函数抛出未捕获异常时，应用现在会以退出码 `1` 自动退出（`app.exit(1)`）。

#### 3. 事件类可阻止语义与低层事件裁剪
- 只有真正支持取消的事件才拥有 `prevent()` 和 `prevented` 属性（继承自 `WindowPreventableEvent` / `AppPreventableEvent`）；非可阻止事件（如 `TitleChangedEvent`、`ClosedEvent`）不再提供 `prevent()`。
- 为避免高频 GIL 获取开销，Rust 侧不再向 Python 派发以下低层输入与帧循环事件（相关枚举与类同步移除）：
  - `MouseInputEvent`、`CursorMovedEvent`、`MouseWheelEvent`、`KeyboardInputEvent`、`ModifiersChangedEvent`、`CursorEnteredEvent`、`CursorLeftEvent`
  - `AppEvent.NewEventsEvent`、`AppEvent.MainEventsClearedEvent`、`AppEvent.RedrawEventsClearedEvent`
  - `_core` 类型 `ModifiersState`、`KeyLocation`、`StartCause`

#### 4. `Window` 方法重命名与行为调整
| 0.1.2 | 0.2.0rc1 | 说明 |
|---|---|---|
| `win.set_size(w, h)` | `win.set_inner_size(w, h)` | 与 `inner_size()` / `set_min_inner_size()` 对齐 |
| `win.minimize(flag=True)` | `win.set_minimized(flag)` | 合并为单一方法，统一同步 WebView 可见性 |
| `win.set_maximize(flag=True)` | `win.set_maximized(flag=True)` | 命名统一 |
| `win.set_enable(enabled)` | `win.set_enabled(enabled)` | 命名统一 |
| `win.focus(flag=True)` / `set_focused` | `win.focus()` | 移除 `flag` 参数及 `set_focused()` |
| `win.set_background_color(r, g, b, a)` | `win.set_background_color((r, g, b, a))` | 改为传入 RGBA 四元组，与 `WindowOptions` 一致 |
| `win._id` | `win.id` | 公开只读属性（同步新增 `win.is_closed`、`win.bridge`） |
| 平台方法在不支持的系统上抛 `AttributeError` | 返回失败的 `Task`（`NotImplementedError`） | 与 `apply_effect()` 行为保持一致 |
| `untrusted=True` 时 `win.emit()` 返回完成态 | 返回失败的 `Task`（`RuntimeError`） | 明确提示不可信模式下无法派发事件 |

#### 5. `WindowOptions(bridge=None)` 与 `WSGI` 调整
- 非 `untrusted` 模式下即使传入 `bridge=None`，窗口也会装配默认 `Bridge()` 并执行生命周期钩子（默认命令表为空，所有未知命令仍被拒绝）。
- `WSGI(..., max_workers=...)` 已废弃并触发 `DeprecationWarning`，请求现统一提交至 `App` 共享线程池（通过 `App(max_workers=...)` 配置）。

---

### 🚀 新增功能（Added）

- **JS Client 与插件生态 (`js/`)**：
  - 使用 TypeScript 重写页面客户端（`esbuild` + `tsc`），输出 ESM/CJS/类型声明（`js/dist/`，npm 包发布计划待定）及 Python 嵌入模块 `_bridge_client.py`。
  - 新增页面向 Python 的单向事件通道：`window.__LUMIVIEW__.emit(event, payload)` 对应后端 `WindowEvent.JsEvent`。
  - 客户端内置 `BridgeError` 类（支持 `instanceof`）、协议版本号 `v`、构建版本号 `build`，以及基于 `EventTarget` 的 `addEventListener` / `removeEventListener` / `listen(event, handler, options)`。
- **事件订阅与等待原语**：
  - `app.on()` 与 `win.on()` 支持 `where=` 同步过滤谓词、支持装饰器与直接传参两种写法，并返回可幂等取消的 `Subscription` 对象。
  - 新增 `app.wait_for(...)`、`win.wait_for(...)` 一次性事件等待器（在宿主关闭时自动以 `AppClosedError` / `WindowClosedError` 结算，支持 `timeout=`）。
  - 新增 `win.wait_loaded(timeout=...)`：在 `Window.create()` 内部预注册 `PageLoadFinishedEvent` 监听，消除页面加载过快导致的竞态。
  - 新增 `WindowEvent.ClosedEvent`。
- **并发与 `Task` 增强**：
  - 新增 `Task.with_timeout(timeout, *, message=...)`（非阻塞超时视图，不影响原 Task 执行）、`Task.on_exception()`。
  - `task()` 与 `run_async()` 现自动向工作线程和异步任务传播 `contextvars`。
  - 新增 `App.windows`、`App.get_window(win_id)`、`App.is_async_thread()`、`App.monitors()`、`App.primary_monitor()`。
- **菜单与类型导出**：
  - 新增只读属性 `Menu.items`（返回 `tuple` 快照）以及保留 `id` 与回调的 `MenuItem.copy()` / `Submenu.copy()`。
  - 添加 `python/lumiview/py.typed`（PEP 561）；顶层包重新导出 `DragDropEvent`、`WindowHandleKind`、`Subscription` 及 `WindowPreventableEvent` / `AppPreventableEvent`。
- **Free-threading 与测试基础设施**：
  - 支持 Python `3.10+`（`cp310-abi3`）、`3.14t`（`cp314-cp314t`）与 `3.15+`（`cp315-abi3.abi3t`）多 ABI 矩阵打包。
  - 新增完整单元与真实窗口端到端 CI 工作流（`.github/workflows/test.yml`）及构建校验脚本（`.github/scripts/`）。

---

### 🔧 改进与修复（Changed & Fixed）

- **Rust 事件循环过滤优化**：在 `run_event_loop_detached` 中先通过 `is_python_event` 过滤事件再获取 GIL，消除无关系统事件带来的 GIL 抖动。
- **停机与并发竞态修复**：
  - 修复 `App` 停机时直接停止事件循环导致协程 `finally` 块丢失的问题，改为 `_finalize_loop()` 取消并等待任务清理后停止循环，并释放 `asyncgens`。
  - `AppEvent.ReadyEvent` 现等待所有处理器完成后再启动 `entry`。
  - 双击 `Ctrl+C` 支持在关闭协商期间强制退出（`exit-now`）。
  - macOS 默认应用菜单中的 `Quit` 改为调用 `App.get().exit()`，使 `Cmd+Q` 走完 `CloseRequestedEvent` 优雅关闭路径。
  - 引入 `App._spawn()` 与锁保护（`_pending_lock`、`_handlers_lock`、`_windows_lock`），消除停机期间的 `"coroutine was never awaited"` 警告与 `call_on_main` 挂死风险。
- **`Window` 可靠性修复**：
  - `eval_js` 与 `emit` 监听 `WindowEvent.ClosedEvent`，窗口在回调返回前关闭时立即以 `WindowClosedError` 结算，不再永久挂起。
  - 窗口创建阶段发生异常时调用 `_teardown_failed_create()` 回滚，避免误触发 `exit_on_last_window`。
  - `Window._on_tao_event` 重构为结构化 `match` 分派。
- **Bridge 与插件修复**：
  - `Scope._register` 缓存函数签名与类型提示，并修复无参数或仅注入 `BridgeContext` 的命令绕过 `strict=True` 多余参数校验的漏洞。
  - `WindowControls` 使用 `WeakKeyDictionary` 按窗口隔离最大化状态（支持多窗口共享插件实例），JS 脚本改用 `Symbol.for` 防止重复绑定，所有控制命令改为 `async def` 直接 `await ctx.window.*`，修复自定义 `name=` 时命令路径不匹配的问题。
- **`Task` 修复**：
  - 修复 `Task.__del__` 调用 `self.exception()` 导致异常被误标为“已读取”从而吞掉未处理异常日志的 Bug，并忽略 `asyncio.CancelledError`。
  - 新增线程安全的 `Task._settle()`，避免并发取消与结算触发 `InvalidStateError`。
- **`Menu` 与 `Serve` 修复**：
  - `Submenu.append` / `insert` / `remove` 改为 `@main_thread` 串行执行，修复多线程连续修改导致数据列表与原生菜单不同步的问题；`MenuItem._native_call` 原子读取 `_inner`。
  - `WSGI` 使用标准库 `io.BytesIO` 并对 `PATH_INFO` 执行 `urllib.parse.unquote()` 解码；`WSGI` / `ASGI` / `Handler` 在停机期间统一返回 `503 Service Unavailable`；`Static` 改用 `email.utils.formatdate` 生成 HTTP 日期头。
- **文档重构**：将 `docs/` 重组为八篇面向任务的中英双语指南（架构与并发、生命周期与事件、窗口与外观、Bridge 与客户端、插件与权限、Serve、菜单与托盘），新增文档导航页并同步更新 README 链接。
- **依赖版本**：`wryview~=0.5.5`、`cattrs~=26.1`、`maturin>=1.16.0`、`pyo3 0.30`。
