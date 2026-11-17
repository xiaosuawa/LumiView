# JS ↔ Python communication (Bridge and client)

LumiView provides two-way communication:
- **Request/response (RPC)**: JS calls `window.__LUMIVIEW__.invoke(command, payload)` and asynchronously receives a Python return value or a structured `BridgeError`.
- **One-way event notifications**:
  - Python → JS: `await win.emit(event, payload)`, received on the JS side with `window.__LUMIVIEW__.listen(event, handler)`.
  - JS → Python: `window.__LUMIVIEW__.emit(event, payload)`, received on the Python side as `WindowEvent.JsEvent`.

---

## Python side: registering commands and handling errors

Register functions with `Bridge` to expose them to the page; plain sync functions (run on the thread pool) and async coroutines (run on the asyncio thread) are both supported:

```python
import asyncio
from dataclasses import dataclass
from lumiview import App, Bridge, BridgeContext, BridgeError, Window, WindowOptions

bridge = Bridge()


@dataclass
class UserInfo:
    name: str
    age: int


@bridge.command
def greet(name: str, count: int = 1) -> str:
    """Parameters are unpacked from the JS payload by function signature; defaults and dataclasses are supported."""
    return f"Hello, {name}! " * count


@bridge.command
async def save_user(ctx: BridgeContext, user: UserInfo) -> dict:
    """Parameters declared as BridgeContext are injected by the runtime, not passed from JS."""
    await asyncio.sleep(0.1)
    # ctx.window: the Window that made the call
    # ctx.command: the full command name (e.g. "save_user")
    # ctx.scope: the Scope node the command is registered on
    # ctx.payload: the raw dict
    await ctx.window.set_title(f"Saved: {user.name}")
    return {"ok": True, "user": user.name}


@bridge.command
def check_auth(token: str) -> None:
    if token != "secret":
        # Raising BridgeError rejects the JS Promise with a structured error
        raise BridgeError(code="unauthorized", message="Invalid token", data={"retry": False})
```

### Parameter binding and strict type checking (`cattrs`)

Command parameters are parsed by `cattrs` with **strict type checking** (no implicit weak coercion):
- **No implicit coercion**: a `bool` is not accepted for `int` or `float`, and the string `"123"` is not converted to `int`; only a float with an integral value (such as `3.0`) may match `int`.
- **No `*args` or `**kwargs`**: a command signature must take fixed parameters.
- **`strict=True` (the default)**: if the `payload` from JS contains extra fields that are not in the function signature (even for a zero-argument command or one that only takes `BridgeContext`), the call is rejected with an `invalid_argument` error. Set `@bridge.command(strict=False)` to pass arbitrary fields through.
- **Complex types**: every annotation `cattrs` can structure is supported, including `dataclass`, `list[T]`, `dict[K, V]` and optional types.

---

## JS side: the injected `window.__LUMIVIEW__` global

Unless `WindowOptions(untrusted=True)` is set, the page gets a read-only, locked-down `window.__LUMIVIEW__` object injected at document start (non-enumerable and not overwritable).

```html
<script>
  const lv = window.__LUMIVIEW__;

  // 1. Call a Python command
  async function run() {
    try {
      const msg = await lv.invoke("greet", { name: "LumiView", count: 2 });
      console.log(msg);
    } catch (err) {
      if (err instanceof lv.BridgeError) {
        console.error(`code=${err.code}, message=${err.message}`, err.data);
      }
    }
  }

  // 2. Listen for events pushed from Python (returns an unsubscribe function)
  const unlisten = lv.listen("app.status", (payload) => {
    console.log("status received:", payload);
  });

  // The standard EventTarget interface also works (the payload is on event.detail)
  lv.addEventListener("app.status", (e) => console.log(e.detail));

  // 3. Send a fire-and-forget event to Python (triggers WindowEvent.JsEvent)
  lv.emit("ui.ready", { theme: "dark" });
</script>
```

Built-in client properties:
- `window.__LUMIVIEW__.v`: the wire protocol version (currently `1`)
- `window.__LUMIVIEW__.build`: the LumiView version that built this client (e.g. `"0.2.0rc1"`)
- `window.__LUMIVIEW__.plugins`: the frontend namespaces injected by plugins (e.g. `plugins.window`)
- `window.__LUMIVIEW__.BridgeError`: the error class, for `instanceof` checks

---

## Frontend tooling: the typed TypeScript facade (`js/`)

If your frontend is built with Vite / Webpack / TypeScript, the `js/` directory in the repo provides a thin facade layer (not published to npm yet; build or reference `js/dist` locally). It reuses the injected `window.__LUMIVIEW__` directly and never creates a second client instance:

```ts
import { invoke, listen, emit, isBridgeError } from "lumiview";
import { windowControls } from "lumiview/window-controls";

// Declaration merging adds end-to-end type checking for commands
declare module "lumiview" {
  interface Commands {
    "greet": { payload: { name: string; count?: number }; result: string };
  }
}

const text = await invoke("greet", { name: "TypeScript" }); // inferred as Promise<string>
const wc = windowControls();                                // defaults to the "window" mount path
await wc.minimize();
```

---

## Security and isolation modes

| Configuration | Effect |
|---|---|
| `WindowOptions(bridge=my_bridge)` | Injects the JS client and allows only commands mounted on `my_bridge` that pass the permission chain |
| `WindowOptions(bridge=None)` (the default) | Injects the JS client but with an empty default `Bridge()`, so **every `invoke` returns `unknown_command`**; `emit` / `listen` still work |
| `WindowOptions(untrusted=True)` | **Injects no client script at all** (`window.__LUMIVIEW__` does not exist); cannot be combined with `bridge=`, and suits loading untrusted third-party pages. A low-level `window.ipc.postMessage(...)` from the page only raises `WindowEvent.WebMessageReceivedEvent` |
