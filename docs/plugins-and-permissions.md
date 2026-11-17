# Scopes, permission chains and custom plugins

LumiView uses **`Scope` (the scope tree) + `ScopePermission` (the permission chain) + `Plugin` (lifecycle hooks)** to organize commands and modular extensions in large applications.

---

## The `Scope` command tree and mounting (`include`)

Create a child scope with `bridge.scope("...")`, or instantiate `Scope("name")` on its own and mount it:

```python
from lumiview import Bridge, Scope

fs_scope = Scope("fs")

@fs_scope.command
def read_text(path: str) -> str:
    ...

bridge = Bridge(includes=[fs_scope])  # JS calls "fs.read_text"
```

### Important constraints on `include()`

`include()` mounts purely — it links the parent/child pointers instead of shallow-copying:
1. **Must be named**: an unnamed instance (`Scope("")`) cannot be mounted.
2. **Mount once**: one `Scope` / `Plugin` instance can be mounted at exactly one position in one tree; mounting it again raises `ValueError` (this prevents the parent pointer from being rewritten and the permission chain from drifting).
3. **No cycles**: it cannot be mounted under its own subtree, and one parent node cannot have two children with the same name.
4. **Dotted scope names**: with `run` registered under `Scope("a.b")`, the command is found as `"a.b.run"` (longest prefix match).

---

## How the `ScopePermission` chain works

Every `Scope` node can be configured with `ScopePermission(allow=..., deny=...)`; patterns use `*` wildcards matched against the command path **relative to the current node**:

```python
from lumiview import Bridge, Scope, ScopePermission

fs = Scope(
    "fs",
    permissions=ScopePermission(
        allow=("read.*",),
        deny=("read.secret",),
    ),
)

@fs.command(name="read.log")
def read_log() -> str:
    return "log"

@fs.command(name="read.secret")
def read_secret() -> str:
    return "secret"

# The root Bridge defaults to allow=("*",); tighten it further on the root if needed
bridge = Bridge(includes=[fs])
```

### Evaluation rules (`check_chain`)

When JS calls a command, the framework checks **from the root node down to the node that holds the command**:

1. **Per-layer semantics**: at each layer, **`deny` always wins over `allow`**; if a layer only has `deny` and an empty `allow` tuple `()`, that layer is a pure blacklist (it rejects only paths matching `deny`).
2. **Unconfigured layers are skipped**: a node with both `allow` and `deny` empty does not take part in filtering.
3. **Fail closed**: if **no layer at all** on the chain has rules configured, the command is **rejected** (`forbidden`). (Note that the `Bridge()` root carries `allow=("*",)` by default, so an ordinary root bridge works out of the box.)
4. **Dynamic changes**: append rules at runtime with `scope.allow("...")` / `scope.deny("...")`.

---

## `Plugin`: a scope with lifecycle hooks

`Plugin` inherits from `Scope` and adds two hooks that fire automatically during `Window.create()`:

- **`on_init(self, ctx: InitContext) -> InitContext`**: runs **before** the native window and WebView are created. Append initialization scripts through `ctx.inject_script`, or register early events through `ctx.window` (such as `PageLoadStartedEvent`).
- **`on_ready(self, window: Window) -> None`**: runs **after** the native window and WebView have been created. Save state or bind window events here (for example, listen to `ResizedEvent` the way `WindowControls` does).

> **Important**: if one `Plugin` instance is mounted on a **`Bridge` shared by several windows**, do not store per-window state directly on `self._window`; use `weakref.WeakKeyDictionary[Window, ...]` to isolate state per window, and use `Symbol.for(...)` in injected scripts to prevent double initialization.

---

## Worked example: a multi-window-safe custom plugin

```python
from lumiview import App, Bridge, BridgeContext, InitContext, Plugin, Window, WindowOptions

SCRIPT_TEMPLATE = """\
(() => {
  const client = window.__LUMIVIEW__;
  if (!client || client.plugins["{{ns}}"]) return;
  client.plugins["{{ns}}"] = {
    ping() { return client.invoke("{{scope}}.ping", {}); },
    notify(text) { return client.invoke("{{scope}}.notify", { text }); },
  };
})();
"""


class MyPlugin(Plugin):
    def __init__(self, name: str = "myplugin") -> None:
        super().__init__(name)
        self.command(self.ping)
        self.command(self.notify)

    def on_init(self, ctx: InitContext) -> InitContext:
        scope_path = self._full_name("")
        ns = scope_path.split(".")[-1]
        script = SCRIPT_TEMPLATE.replace("{{scope}}", scope_path).replace("{{ns}}", ns)
        ctx.inject_script += "\n" + script
        return ctx

    def on_ready(self, window: Window) -> None:
        # Set up per-window listeners here
        pass

    async def ping(self, ctx: BridgeContext) -> str:
        return f"pong from window {ctx.window.id}"

    async def notify(self, ctx: BridgeContext, text: str) -> None:
        # scope.emit adds the namespace prefix automatically -> "myplugin.notified"
        ctx.scope.emit("notified", {"text": text}, window=ctx.window)


app = App(name="PluginDemo")
bridge = Bridge(includes=[MyPlugin()])

HTML = """<!doctype html>
<script>
  window.__LUMIVIEW__.listen("myplugin.notified", (p) => alert(p.text));
  window.__LUMIVIEW__.plugins.myplugin.ping().then(console.log);
</script>
"""


async def main():
    await Window.create(WindowOptions(html=HTML, bridge=bridge, devtools=True))


if __name__ == "__main__":
    app.run(main)
```
