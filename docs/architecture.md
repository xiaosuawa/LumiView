# Architecture

LumiView is small on purpose: one Rust extension that wraps tao (windows / event
loop), wry (WebView), muda (menus) and tray-icon, plus a Python layer that turns
them into an async-first, thread-safe API.

```
Your code
   │
   ▼
lumiview.*            App, Window, Bridge, Menu, Tray, Serve, Task   (Python)
   │
   ▼
lumiview._core        PyO3 bindings: TaoEventLoop, TaoWindow, ...     (Rust)
   │
   ▼
tao  wry  muda  tray-icon  window-vibrancy                            (Rust crates)
   │
   ▼
OS window + system WebView
```

The page side is a separate TypeScript client (`js/`, injected as
`window.__LUMIVIEW__`), see [js-client.md](js-client.md).

## Threads

| Thread | Runs |
|---|---|
| **Main** | The tao event loop and every native window / WebView call |
| **asyncio** | Your `async` code: the `entry` function, `async` handlers, `async` commands, ASGI apps |
| **Thread pool** | Sync `task()` calls, sync handlers, sync commands, WSGI apps |

`App(max_workers=N)` sizes the pool (default 6). The asyncio loop has a thread of
its own and is created by `app.run()`.

Rules that follow from this:

- Native objects (`TaoWindow`, `WebView`) are **unsendable**: touching them from
  another thread crashes. `Window` marshals every call through `app.call_on_main`.
- Handlers never run on the GUI thread, so a handler may `await` freely but must
  not call native APIs directly.
- The GUI thread must never block on a `Task` for long — see below.

## Tasks

Every cross-thread or delayed operation returns `Task[T]`, a
`concurrent.futures.Future` subclass:

```python
result = await handle                # asyncio thread — preferred
result = handle.result()             # blocking, non-asyncio thread
handle.on_done(callback)             # no blocking
handle.on_exception(callback)
```

`Task.result()` has thread-dependent behaviour:

| Called from | Behaviour |
|---|---|
| asyncio thread | raises `TaskDeadlockError` (it would deadlock the loop) |
| GUI thread | drains the main-thread command queue while waiting — the window freezes |
| any other thread | blocks normally |

`task(fn, *args)` schedules a function and wraps it: `async` functions go to the
asyncio loop, plain functions to the pool. `app.call_on_main(fn, ...)` is the only
bridge to the GUI thread — on it, `fn` runs inline; elsewhere it is queued and
drained by the tao callback loop.

A `Task` that fails and whose exception is never retrieved logs an error when it is
garbage-collected; don't silently drop failures.

## Events

```
tao event
  → lumiview._core builds a TaoEvent subclass (ResizedEvent, ...)
  → App._on_tao_event (main thread) routes by window id
  → Window._emit(event): find handlers by type, run `where` filters
  → handlers: async on the asyncio loop, sync on the thread pool
```

- Handlers are registered with `win.on(EventClass, where=...)`; `where` is a
  synchronous `(event) -> bool` filter function typed against the concrete event
  class. A filter that raises is treated as a non-match and logged — it never
  breaks dispatch.
- `win.on(...)` / `app.on(...)` return a `Subscription`; `.cancel()` removes the
  handler (idempotent). A dispatch already in flight may still call it once.
- `event.window` is filled in before dispatch.
- `_emit` returns a `Task` that completes when every handler is done (or `None`
  when nobody is listening).
- **Preventable events** (`CloseRequested`, `NavigationRequested`,
  `NewWindowRequested`, `DownloadStarted`) come from synchronous WebView callbacks.
  LumiView dispatches them and blocks the callback until the handlers finish, then
  checks `event.prevented` — that is why handlers for these events must not block on
  the GUI thread.
- `wait_for(...)` is one-shot: it registers the target handler plus an internal
  close handler, resolves with the next match, and removes both. `Window.wait_for`
  treats `ClosedEvent` as "too late" (`WindowClosedError`); `App.wait_for` uses
  `AppCloseEvent` (`AppClosedError`). `wait_loaded()` is the same mechanism
  pre-registered at creation time, so it cannot race the page load.

## Application lifecycle

```
CREATED ──run()──▶ STARTING ──▶ RUNNING ──exit()──▶ STOPPING ──▶ STOPPED
```

- `run(entry)` must be called once from the main thread and blocks until exit.
- When the app is ready, `AppEvent.ReadyEvent` is dispatched and `entry` is started.
  A failure in either exits with code 1 (the first exit request wins).
- `exit(code)` records the request (first request wins), immediately stops
  admitting cross-thread work — `call_on_main`, `wait_for`, bridge invokes and
  serve requests fail fast with `AppClosedError` / an error response — and wakes
  the loop. Cleanup happens in one place.
- `app.windows` / `app.get_window(id)` / `win.id` / `win.is_closed` are
  lock-protected reads; `app.async_loop` is `None` before `run()` and during
  shutdown, so third-party threads can check it before scheduling work.
- Shutdown order: stop accepting work → close every window (dispatch `ClosedEvent`)
  → drop tray icons → drop menus → dispatch `AppCloseEvent` → cancel pending asyncio
  tasks → stop the loop → fail outstanding main-thread handles → close the pool.
- Runtime exceptions in handlers, commands, serve callbacks or `call_on_main` are
  logged, never fatal. Exceptions during startup (`entry`, Ready handler,
  `prepare`) fail the launch.

`Ctrl+C` posts `app.exit()` to the asyncio loop; calling `exit()` directly from the
signal handler could re-enter a lock the main thread already holds.

## The JS bridge

```
page                                       Python
────                                       ──────
__LUMIVIEW__.invoke(cmd, payload)
  → window.ipc.postMessage(JSON)   ──▶  Bridge._on_message(raw)
                                          permission chain → bind_arguments
                                          run command off the GUI thread
  ◀── eval_js "dispatch({...})"          Bridge._respond(...)
promise resolved / rejected
```

- `window.ipc.postMessage` is wry's channel; it exists in every LumiView window.
- Python → page is `eval_js` into the single `dispatch()` entry point.
- `invoke` goes through the permission chain (`Scope` tree) before binding.
- Commands run off the GUI thread; `async def` on the asyncio loop, `def` on the pool.
- `Bridge` owns the command tree for the window's lifetime; `Window.bridge` is a
  read-only getter (`None` in untrusted mode). Register commands on it in place.
- `untrusted=True` disables both directions: no client is injected and incoming
  messages are not parsed.

Details: [plugins.md](plugins.md) and [js-client.md](js-client.md).

## Modules

| Module | Responsibility |
|---|---|
| `lumiview.app` | `App` singleton, state machine, `run`/`exit`, `call_on_main`, event bus |
| `lumiview.window` | `Window`, `WindowOptions`, `WebContext`, native window + WebView |
| `lumiview.events` | Event classes and the `WindowEvent` / `AppEvent` namespaces |
| `lumiview.task` | `Task`, `task()`, `run_async()`, deadlock rules |
| `lumiview.bridge` | `Bridge`, `BridgeError`, IPC dispatch, injected JS client |
| `lumiview.scope` | `Scope` tree, permissions, `Plugin`, `BridgeContext` / `InitContext` |
| `lumiview._binding` | Payload → Python signature binding (strict) |
| `lumiview.menu` / `lumiview.tray` | Native menus and tray icons (data wrappers, materialized on the GUI thread) |
| `lumiview.serve` | `lumiview://` protocol: `Static`, `Handler`, `WSGI`, `ASGI` |
| `lumiview.utils` | public helpers: pattern matching, navigation policy |
| `lumiview._utils` | internal helpers (`Task` glue, `Subscription`, wait helpers, `main_thread`) |
| `lumiview.plugins` | Built-in `WindowControls` |
| `lumiview._core` | Rust bindings (tao/wry/muda/tray-icon) |

## Design principles

1. **One `Task` type** — every cross-thread or delayed call returns `Task[T]`;
   no context-dependent auto-unwrapping.
2. **No forced project structure** — LumiView supplies a window + WebView runtime,
   not a scaffold, config file or frontend convention.
3. **Pythonic, sync and async** — the same API works in both worlds; only the
   consumption style changes (`.result()` vs `await`).
4. **Fail loudly at the edges, log during runtime** — startup errors abort; runtime
   errors are logged and the app keeps running.
