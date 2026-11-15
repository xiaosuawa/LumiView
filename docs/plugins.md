# IPC: Commands, Scopes and Plugins

The bridge exposes Python functions to the page. A call from JavaScript goes through
a permission chain, is bound to the Python signature, runs off the GUI thread, and
comes back as a `Promise`. There is no HTTP server and no manual serialization.

## Minimal command

```python
from lumiview import App, Bridge, BridgeContext, Window, WindowOptions

app = App(name="BridgeDemo")
bridge = Bridge()


@bridge.command
def greet(ctx: BridgeContext, name: str = "world") -> str:
    return f"Hello, {name}!"


async def main() -> None:
    win = await Window.create(WindowOptions(
        html="<button id=go>Greet</button><script>"
             "document.getElementById('go').onclick = async () => {"
             "  alert(await window.__LUMIVIEW__.invoke('greet', {name: 'LumiView'}));"
             "};</script>",
        bridge=bridge,
    ))


app.run(main)
```

- Command names are dotted paths through the scope tree. A command registered on the
  root is just `greet`; on a scope named `greeter` it becomes `greeter.greet`.
- The return value is JSON-encoded to the page (anything not JSON-serializable raises
  `internal_error`).
- `async def` commands are awaited on the asyncio loop; plain `def` commands run on
  the thread pool. Neither runs on the GUI thread.

## Binding rules

Payload keys bind to parameter names:

```python
@bridge.command
def search(ctx: BridgeContext, query: str, limit: int = 20) -> list[str]:
    ...
```

- No `*args` / `**kwargs` in commands — registration raises `ValueError`.
- Unknown payload keys are rejected (`invalid_argument`) unless the command is
  registered with `strict=False`.
- Missing required parameters raise `invalid_argument`; values are type-checked
  strictly (no `"3"` → `3` coercion).
- `BridgeContext` is injected, not passed by the page. Fields: `window`, `payload`
  (the raw payload), `command` (full name), `scope` (the registration node).
- Registration options: `@bridge.command(name="custom", replace=True, strict=False)`.

Raise `BridgeError` to return a structured error instead of crashing:

```python
from lumiview import BridgeError

@bridge.command
def read(path: str) -> str:
    try:
        return open(path).read()
    except FileNotFoundError:
        raise BridgeError("not_found", "No such file", {"path": path})
```

The page sees `Error` with `name === "BridgeError"`, `code === "not_found"` and
`data === {"path": ...}`.

## Scopes and plugins

A `Scope` is a named node in the command tree; a `Plugin` is a `Scope` with
window-lifecycle hooks.

```python
from lumiview import Bridge, BridgeContext, ScopePermission
from lumiview.scope import InitContext, Plugin


class Greeter(Plugin):
    def __init__(self) -> None:
        super().__init__("greeter")
        self.command(self.greet)

    def on_init(self, ctx: InitContext) -> InitContext:
        # Runs before the tao window / WebView exist. Append page JS and/or
        # register early event handlers here.
        ctx.inject_script += "window.__greeterReady = true;"
        return ctx

    def on_ready(self, window) -> None:
        # Runs once, after the WebView and page are created.
        print("greeter ready on", window)

    def greet(self, ctx: BridgeContext, name: str = "world") -> str:
        return f"Hello, {name}!"


bridge = Bridge(includes=[Greeter()])
```

- `on_init` is called for every plugin in tree order; return the (possibly modified)
  `InitContext` to keep accumulating `inject_script`.
- `on_ready` is called once per window that uses this bridge.
- `InitContext` also carries `window` (the shell) and `options` (the
  `WindowOptions` being applied) — the only safe place to subscribe to events that
  fire before `Window.create()` returns.

## Permissions

Each node carries `allow` / `deny` patterns. Patterns are `*` globs matched against
the command path **relative to that node** — `*` matches anything, including dots.

```python
from lumiview import Bridge, ScopePermission

bridge = Bridge(
    includes=[Greeter()],
    permissions=ScopePermission(
        allow=("greeter.*",),
        deny=("greeter.secret",),
    ),
)
```

Semantics of the chain (command node → root):

- `deny` wins over `allow`.
- An empty `allow` list means "no whitelist" (blacklist-only).
- Nodes with no rules are skipped.
- If **no** node on the chain has any rule, the call is rejected — safe by default.
- The `Bridge` root is initialized with `allow=("*",)` unless you pass
  `permissions=`.

Rules can be appended at runtime: `scope.allow("x.*")`, `scope.deny("x.y")`.

## Mounting shared scopes

`Scope.include(other)` mounts a subtree without copying or merging it. Names and
permissions are relative, so a shared subtree keeps working wherever it is mounted.

```python
from lumiview import Bridge
from lumiview.scope import Scope, ScopePermission

fs = Scope("fs", permissions=ScopePermission(allow=("read.*",)))
bridge = Bridge()
bridge.include(fs)          # commands become fs.read.*
```

Constraints: the scope must be named, can be mounted exactly once, and cannot be
mounted under its own subtree. To mount under a different name, construct it with
that name.

## JS side

```js
const { invoke, listen } = window.__LUMIVIEW__;

const greeting = await invoke("greeter.greet", { name: "LumiView" });
const unlisten = listen("greeter.changed", (payload) => console.log(payload));
```

Plugins expose their JS API under `plugins`, keyed by the mount name:

```js
const greeter = window.__LUMIVIEW__.plugins.greeter;
```

See [js-client.md](js-client.md) for the full page-side reference.

Pushing events from Python: `window.emit()` (full event name) or
`ctx.scope.emit("changed", payload, window=ctx.window)` (auto-prefixed with the
scope path).

## Runtime behaviour

- `Window.bridge` is a read-only getter and lives for the window's lifetime.
  Register commands on it in place (`win.bridge.command(...)`); whole-tree
  replacement is not supported — the injected client and the plugin
  `on_init` / `on_ready` hooks belong to the tree created with the window.
- `bridge=None` still injects the client (so `emit()` / `listen()` work), but every
  `invoke()` resolves with `unknown_command`.
- `WindowOptions(untrusted=True)` injects nothing **and** leaves IPC messages
  unparsed; raw messages surface as `WindowEvent.WebMessageReceivedEvent`, and
  `win.bridge` is `None`.

## WindowControls

The built-in `WindowControls` plugin adds a custom-titlebar API, declarative drag
regions, plus maximize/fullscreen syncing:

```python
from lumiview import Bridge, WindowOptions
from lumiview.plugins import WindowControls

bridge = Bridge(includes=[WindowControls()])

win = await Window.create(WindowOptions(
    decorations=False,
    bridge=bridge,
    html="""
      <header data-lumiview-drag-region class="titlebar">
        <span>My App</span>
        <button onclick="__LUMIVIEW__.plugins.window.minimize()">—</button>
        <button onclick="__LUMIVIEW__.plugins.window.toggleMaximize()">□</button>
        <button onclick="__LUMIVIEW__.plugins.window.close()">×</button>
      </header>
    """,
))
```

- `data-lumiview-drag-region` makes an area drag the window with no JavaScript;
  `data-lumiview-resize-region="east"` (etc.) makes an in-client resize handle.
- Buttons call the JS API directly. It lives at `__LUMIVIEW__.plugins.<mount name>`:
  `plugins.window.minimize()` for the default mount; with
  `WindowControls(name="titlebar")` the commands become `titlebar.*` and the API
  `plugins.titlebar`.

  | JS API | Bridge command | Result |
  |---|---|---|
  | `minimize()` | `window.minimize` | — |
  | `toggleMaximize()` | `window.toggle_maximize` | `bool` |
  | `isMaximized()` | `window.is_maximized` | `bool` |
  | `close()` | `window.close` | — |
  | `startDragging()` | `window.start_dragging` | — |
  | `startResizeDragging(direction)` | `window.start_resize_dragging` | — |
  | `onMaximizedChange(fn)` | listens to `window.maximized-changed` | unsubscribe fn |

- Bundled frontends can skip the global and import the typed module instead:

  ```ts
  import { windowControls } from "lumiview/window-controls";

  const wc = windowControls();          // or windowControls("titlebar")
  await wc.minimize();
  const unlisten = wc.onMaximizedChange((maximized) => console.log(maximized));
  ```

- Window-edge resizing is native (WM_NCHITTEST on Windows / tao elsewhere); don't
  cover the border with a resize region.
- `WindowControls(name="x", drag_regions=False, link_fullscreen=False,
  link_maximized=False)` configures the pieces. The drag/fullscreen hooks are
  installed once per page (first instance wins); extra instances are controlled
  through their JS API.
