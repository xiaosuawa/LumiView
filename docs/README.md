# LumiView Documentation

LumiView is a Python desktop application framework built on [tao](https://github.com/tauri-apps/tao) and wry (via [wryview](https://github.com/xiaosuawa/wryview)): Rust drives native windows and the system WebView (Windows WebView2 / macOS WKWebView / Linux WebKitGTK), while the Python layer provides an **async-first, thread-safe API that is identical in sync and async code**.

## The mental model in three minutes

When using LumiView, you only need to remember four core ideas:

1. **Three threads, each with a clear job**:
   - **Main thread** — owns the `tao` event loop and every native window/WebView call.
   - **asyncio thread** — runs your `main` entry point and async event/command callbacks.
   - **Thread pool** — automatically hosts your sync event callbacks, sync Bridge commands and WSGI requests.
2. **`Task[T]` works both ways** — every operation that touches native windows across threads returns a `Task[T]`: `await` it in async code, call `.result()` on it in sync code.
3. **Two core event namespaces** — `AppEvent.*` for application-level events and `WindowEvent.*` for window-level events; both support `on()`, `where=` filters, cancellable `Subscription`s and one-shot `wait_for()`.
4. **Two front-end channels** — structured RPC and custom events over `Bridge` (the page-side client is injected as `window.__LUMIVIEW__`); static front-end assets or FastAPI/Django/Flask apps over the `serve` protocol (`lumiview://`).

---

## Documentation

| Chapter | What it covers |
|---|---|
| [Getting Started](getting-started.md) | Installation, minimal async/sync apps, `WindowOptions`, multi-window shared contexts and logging |
| [Architecture & Concurrency](architecture-and-concurrency.md) | Layered architecture, threading model, advanced `Task[T]` usage, deadlock protection and third-party GUI integration |
| [Lifecycle & Events](lifecycle-and-events.md) | `AppState`, two-phase graceful shutdown, preventable events, event filters and `wait_for` / `wait_loaded` |
| [Windows & Native Appearance](window-and-appearance.md) | Window geometry and state, frameless custom titlebars, native blur effects and WebView capabilities |
| [JS ↔ Python Communication](bridge-and-js-client.md) | The `window.__LUMIVIEW__` client, command binding and argument validation, the TypeScript facade and secure modes |
| [Plugins & Permissions](plugins-and-permissions.md) | The `Scope` command tree, `ScopePermission` chains, `Plugin` lifecycle hooks and a custom-plugin walkthrough |
| [Serve Protocols](serve-protocols.md) | Running local assets and web frameworks without a port: `Static`, `Handler`, `WSGI` (Django/Flask) and `ASGI` (FastAPI) |
| [Native Menus & Tray](menus-and-tray.md) | Data-only menu trees, accelerators and callbacks, macOS/Windows menu bars and cross-platform tray-resident apps |

> Chinese translations live next to the English docs (`docs/*.zh.md`), starting with
> [文档导航](README.zh.md).
