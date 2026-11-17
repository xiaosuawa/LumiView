# 作用域、权限链与自定义插件

LumiView 使用 **`Scope`（作用域树） + `ScopePermission`（权限链） + `Plugin`（生命周期钩子）** 来组织大型应用的命令与模块化扩展。

---

## `Scope` 命令树与挂载（`include`）

可以通过 `bridge.scope("...")` 创建子作用域，或独立实例化 `Scope("name")` 后挂载：

```python
from lumiview import Bridge, Scope

fs_scope = Scope("fs")

@fs_scope.command
def read_text(path: str) -> str:
    ...

bridge = Bridge(includes=[fs_scope])  # JS 侧调用 "fs.read_text"
```

### `include()` 的重要约束

`include()` 采用**纯挂载（引用父子指针）**机制，而非浅拷贝：
1. **必须具名**：未命名（`Scope("")`）的实例不能被挂载。
2. **单次挂载**：同一个 `Scope` / `Plugin` 实例只能被挂载到一棵树中的一个位置，重复挂载会抛出 `ValueError`（防止父指针被改写导致权限链漂移）。
3. **禁止环路**：不能挂载到自身子树下，且同一父节点下不能挂载同名子节点。
4. **作用域名称支持点号**：例如 `Scope("a.b")` 下注册 `run`，可用 `"a.b.run"` 精确查找（采用最长前缀匹配）。

---

## `ScopePermission` 权限链机制

每个 `Scope` 节点都可以配置 `ScopePermission(allow=..., deny=...)`，规则使用 `*` 通配符匹配**相对于当前节点**的命令路径：

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

# 根 Bridge 默认 allow=("*",)，也可以在根上进一步收紧
bridge = Bridge(includes=[fs])
```

### 判定规则（`check_chain`）

当 JS 调用某条命令时，框架会从**根节点一路向下检查到命令所在的节点**：

1. **单层语义**：在每一层中，**`deny` 永远优先于 `allow`**；如果某层只写了 `deny` 而 `allow` 为空元组 `()`，表示该层是纯黑名单（只拒绝匹配 `deny` 的路径）。
2. **未配置层跳过**：`allow` 和 `deny` 均为空的节点不参与拦截。
3. **默认拒绝（Fail-Closed）**：如果整条链上**没有任何一层**配置过规则，命令将被**拒绝**（返回 `forbidden`）。（注意：`Bridge()` 根节点默认带有 `allow=("*",)`，因此普通根桥接开箱即用。）
4. **动态修改**：可在运行期通过 `scope.allow("...")` / `scope.deny("...")` 追加规则。

---

## `Plugin`：带生命周期钩子的作用域

`Plugin` 继承自 `Scope`，额外提供两个在 `Window.create()` 期间自动触发的钩子：

- **`on_init(self, ctx: InitContext) -> InitContext`**：在原生窗口和 WebView **创建之前**执行。可通过 `ctx.inject_script` 追加初始化脚本，或通过 `ctx.window` 注册早期事件（如 `PageLoadStartedEvent`）。
- **`on_ready(self, window: Window) -> None`**：在原生窗口与 WebView **创建完成之后**执行。可在此保存状态或绑定窗口事件（如像 `WindowControls` 一样监听 `ResizedEvent`）。

> **重要**：同一个 `Plugin` 实例如果挂载到被**多个窗口共享的 `Bridge`** 上，不要把单窗口状态直接存成 `self._window`，建议使用 `weakref.WeakKeyDictionary[Window, ...]` 按窗口隔离状态，并在注入脚本中使用 `Symbol.for(...)` 防止重复初始化。

---

## 实战示例：编写一个多窗口安全的自定义插件

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
        # 可在此初始化每窗口的监听
        pass

    async def ping(self, ctx: BridgeContext) -> str:
        return f"pong from window {ctx.window.id}"

    async def notify(self, ctx: BridgeContext, text: str) -> None:
        # 使用 scope.emit 自动加上命名空间前缀 -> "myplugin.notified"
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
