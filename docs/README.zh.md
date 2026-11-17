# LumiView 文档

LumiView 是一个基于 [tao](https://github.com/tauri-apps/tao) 与 wry（[wryview](https://github.com/xiaosuawa/wryview)）构建的 Python 桌面应用框架：底层由 Rust 驱动系统原生窗口与系统 WebView（Windows WebView2 / macOS WKWebView / Linux WebKitGTK），上层提供**异步优先、线程安全、同步/异步统一**的 Python API。

## 3 分钟建立心智模型

使用 LumiView 时，只需要记住以下四个核心设计：

1. **三个线程各司其职**：
   - **主线程**：独占 `tao` 事件循环与所有原生窗口/WebView 调用。
   - **asyncio 线程**：运行你的 `main` 入口函数和异步事件/命令回调。
   - **线程池**：自动托管你的同步事件回调、同步 Bridge 命令和 WSGI 请求。
2. **`Task[T]` 一体两用**：所有跨线程触碰原生窗口的操作都返回 `Task[T]`——在异步函数里 `await`，在同步函数里 `.result()`。
3. **两个核心事件命名空间**：应用级用 `AppEvent.*`，窗口级用 `WindowEvent.*`；支持 `on()`、`where=` 过滤、可取消的 `Subscription`，以及一次性 `wait_for()`。
4. **两条前后端通道**：结构化 RPC + 自定义事件用 `Bridge`（页面侧注入 `window.__LUMIVIEW__`）；加载前端静态资源或直接托管 FastAPI/Django/Flask 用 `serve` 协议（`lumiview://`）。

---

## 文档目录

| 章节 | 内容 |
|---|---|
| [快速入门](getting-started.zh.md) | 安装、异步/同步最小应用、`WindowOptions`、多窗口共享上下文与日志调试 |
| [架构与并发模型](architecture-and-concurrency.zh.md) | 分层架构、线程模型、`Task[T]` 进阶用法、死锁防护与第三方 GUI 集成 |
| [生命周期与事件系统](lifecycle-and-events.zh.md) | `AppState`、两阶段优雅退出、可阻止事件、事件过滤与 `wait_for` / `wait_loaded` |
| [窗口管理与原生外观](window-and-appearance.zh.md) | 窗口几何与状态控制、无边框自定义标题栏、原生毛玻璃特效与 WebView 能力 |
| [JS ↔ Python 通信](bridge-and-js-client.zh.md) | `window.__LUMIVIEW__` 客户端、命令绑定与参数校验、TypeScript 门面与安全模式 |
| [插件与权限系统](plugins-and-permissions.zh.md) | `Scope` 命令树、`ScopePermission` 权限链、`Plugin` 生命周期钩子与自定义插件实战 |
| [Serve 自定义协议](serve-protocols.zh.md) | 免端口运行本地资源与 Web 框架：`Static`、`Handler`、`WSGI`（Django/Flask）与 `ASGI`（FastAPI） |
| [原生菜单与系统托盘](menus-and-tray.zh.md) | 纯数据菜单树、快捷键与回调、macOS/Windows 菜单栏以及跨平台托盘常驻模式 |

> 英文版见 [README.md](README.md)（各章节为 `docs/*.md`）。
