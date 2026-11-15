# JS Client

The page half of the bridge is a single global, `window.__LUMIVIEW__`. The runtime
injects it at document start, before any page script runs.

| Member | Description |
|---|---|
| `invoke(command, payload?)` | Call a Python command; returns a `Promise` |
| `emit(event, payload?)` | Fire-and-forget event to Python (`WindowEvent.JsEvent`) |
| `listen(event, handler, options?)` | Subscribe to events from Python; returns an unsubscribe function |
| `addEventListener` / `removeEventListener` | The underlying `EventTarget` (isolated from DOM events) |
| `dispatch(message)` | Python → page entry point, used by the runtime |
| `plugins` | Namespace container for injected plugin APIs (e.g. `plugins.window`) |
| `v` / `build` | Wire protocol version / LumiView version that injected this client |
| `BridgeError` | Error class used for rejected `invoke()` calls |

The global is installed with `Object.defineProperty`: it is non-enumerable (invisible
to `Object.keys(window)`), cannot be replaced, and its core methods are read-only, so
page code cannot hijack `dispatch`. The object itself stays extensible — plugins add
namespaces under `plugins`.

## Without a bundler

```html
<script>
  const { invoke, listen } = window.__LUMIVIEW__;

  const unlisten = listen("greeter.changed", (payload) => {
    console.log(payload);
  });

  const greeting = await invoke("greeter.greet", { name: "LumiView" });
</script>
```

`emit()` is fire-and-forget; Python receives it as `WindowEvent.JsEvent`:

```python
from lumiview import WindowEvent

@win.on(WindowEvent.JsEvent, where=lambda e: e.event == "form.submitted")
async def on_submitted(event):
    print(event.payload)
```

`emit()` does not go through the permission chain — it is a notification, not a
command. Treat `JsEvent` payloads as untrusted page input and validate them in the
handler. `untrusted=True` windows never receive the client, so they cannot emit.

## With a bundler: the npm package

```bash
npm install lumiview
```

```ts
import { invoke, listen } from "lumiview";
```

The package is a **typed facade** over the installed client. It never creates a
second client, so pending calls and listeners always live in one place. If the page
is not running inside a LumiView window (or the window was created with
`untrusted=True`), `invoke()` rejects immediately with an explanatory error.

### Typed commands

Declare the command map once and `invoke()` becomes end-to-end typed:

```ts
declare module "lumiview" {
  interface Commands {
    "greeter.greet": { payload: { name?: string }; result: string };
    "counter.get": { result: number };
  }
}

const greeting = await invoke("greeter.greet", { name: "x" }); // string
const count = await invoke("counter.get");                     // number

// @ts-expect-error — `name` must be a string
await invoke("greeter.greet", { name: 1 });
```

Undeclared commands are still callable, but payload and result are `unknown`:

```ts
const raw = await invoke("debug.dump");        // Promise<unknown>

import { invokeAs } from "lumiview";
const pinned = await invokeAs<number>("debug.dump");
```

### Helpers

| Export | Purpose |
|---|---|
| `isLumiView()` | `true` when the page runs inside a LumiView window with a live client |
| `getClient()` | The raw `window.__LUMIVIEW__` object (throws when missing) |
| `protocol()` | Wire protocol version reported by the injected client |
| `build()` | LumiView version that injected the client |
| `isBridgeError(error)` | Type guard for errors carrying `code` / `data` |

Use `isLumiView()` rather than sniffing the user agent.

## Errors

A Python command raising `BridgeError(code, message, data)` rejects the `Promise`
with an `Error` whose `name` is `"BridgeError"` and which carries `code` and `data`:

```ts
import { invoke, isBridgeError } from "lumiview";

try {
  await invoke("admin.shutdown");
} catch (error) {
  if (isBridgeError(error)) {
    console.log(error.code, error.data);
  }
}
```

Every other failure (unknown command, permission denial, unhandled Python exception)
arrives the same way, with codes such as `unknown_command`, `forbidden`,
`invalid_argument` or `internal_error`.

## Wire protocol

`invoke` / `emit` travel page → Python through wry's `window.ipc.postMessage`.
Python → page uses `eval_js` and a single entry point, `dispatch()`.

| Direction | Message |
|---|---|
| page → Python | `{v: 1, type: "invoke", id, command, payload}` |
| page → Python | `{v: 1, type: "emit", event, payload}` |
| Python → page | `{type: "resolve", id, value}` |
| Python → page | `{type: "reject", id, error: {code, message, data?}}` |
| Python → page | `{type: "event", event, payload}` |

Response ids are per-client sequence numbers (`"1"`, `"2"`, ...). The shape is a
public contract: the injected client and the npm package are versioned together
(`v` / `build` let you spot a mismatch). If `v` is not the protocol the Python
runtime speaks, or `build` differs from the Python package version, rebuild the
injected client (`npm --prefix js run build`) or install the matching `lumiview`
npm package.

## `untrusted=True`

`WindowOptions(untrusted=True)` is two switches at once: nothing is injected **and**
bridge messages are left unparsed. In that window:

- `typeof window.__LUMIVIEW__ === "undefined"`;
- every `window.ipc.postMessage(...)` surfaces as `WindowEvent.WebMessageReceivedEvent`;
- `Window.emit()` returns a failed `Task`.

Use it for pages you do not control. Everything else should keep the client.

## Plugin namespaces

Plugins injected from Python register their JS API under `plugins`, keyed by the
mount name — the client object itself only carries the core members:

```js
// default WindowControls mount
await window.__LUMIVIEW__.plugins.window.minimize();

// a plugin mounted as `WindowControls(name="titlebar")`
await window.__LUMIVIEW__.plugins.titlebar.close();
```

The built-in `WindowControls` also ships a typed npm entry point that calls the
plugin's commands directly (no global needed):

```ts
import { windowControls } from "lumiview/window-controls";

const wc = windowControls();            // or windowControls("titlebar")
await wc.minimize();
const unlisten = wc.onMaximizedChange((maximized) => console.log(maximized));
```

Its drag regions stay declarative, so only the buttons need a call into the API:

```html
<header data-lumiview-drag-region>
  <span>My App</span>
  <button onclick="__LUMIVIEW__.plugins.window.close()">×</button>
</header>
```

See [plugins.md](plugins.md#windowcontrols) for the full titlebar example.

## Building the client (contributors)

The client lives in `js/src` (TypeScript) and is built into two artifacts:

```bash
npm --prefix js install
npm --prefix js run build    # js/dist/* + python/lumiview/_bridge_client.py
```

The generated `python/lumiview/_bridge_client.py` is git-ignored but required at
runtime; without it, `Window.create` raises a `RuntimeError` telling you to run the
build. CI runs the same command before building wheels and the sdist, and
`npm --prefix js test` exercises the client through Node's test runner.
