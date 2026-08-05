# 自定义插件

插件 = 命名空间（`Scope`）+ 生命周期钩子（`Plugin`）+ 命令注册（`command`）。通过 `Bridge` 组合进窗口：

```python
from lumiview import App, Bridge, ScopePermission, Window, WindowOptions

bridge = Bridge(
    includes=[MyPlugin("myplugin")],
    permissions=ScopePermission(allow=("*",)),
)
```

- `Bridge` 内部是一个匿名根 `Scope`；`includes=[...]` 把插件挂到根上（纯挂载，见下）。
- 根权限默认 `allow=("*",)`；传入 `permissions=` 可收紧整棵树的权限链。
- `WindowOptions(bridge=bridge)` 把桥接入窗口；`bridge=None` 则完全禁用 IPC。

## Plugin 子类

```python
from lumiview import BridgeContext
from lumiview.events import WindowEvent
from lumiview.scope import InitContext, Plugin


class Greeter(Plugin):
    def __init__(self):
        super().__init__("greeter")
        self.command(self.greet)          # 注册命令（可加 name=/replace=）

    def on_init(self, ctx: InitContext) -> InitContext:
        """窗口创建时（tao/webview 之前）调用。"""
        ctx.inject_script += "console.log('greeter ready');"
        # ctx.window — 构建中的 Window 空壳（hooks 已就绪），可注册早期事件：
        ctx.window.on(WindowEvent.PageLoadStartedEvent)(
            lambda event: print("early:", event.url)
        )
        return ctx

    def on_ready(self, window: Window) -> None:
        """窗口创建完成后调用一次（拿到完整 Window）。"""
        self._window = window

    def greet(self, ctx: BridgeContext, name: str = "world") -> str:
        """JS 可调用命令：payload 按参数名绑定（cattrs），BridgeContext 自动注入。"""
        return f"Hello, {name}!"
```

- `on_init` 返回的 `InitContext` 会被继续传递（注入脚本累积）；不返回则沿用原值。
- 命令签名规则：不能使用 `*args` / `**kwargs`；普通参数从 JS payload 按名字绑定；`BridgeContext` 是注入参数（字段：`window` / `payload` / `command` / `scope`）。
- 命令内抛 `BridgeError(code, message)` 会结构化成错误返回给 JS（而不是崩溃）。

## JS 侧

`window.lumiview` 在页面加载时自动注入：

```js
// 调用 Python 命令 —— 返回 Promise
const result = await window.lumiview.invoke("greeter.greet", { name: "LumiView" });

// 订阅 Python 主动推送的事件
const unlisten = window.lumiview.listen("greeter.changed", (payload) => {
  console.log(payload);
});
```

Python 主动推送（自定义命名事件走 `Window.emit`，与事件类体系互不冲突）：

```python
# 在命令里（scope.emit 自动加命名空间前缀）
ctx.scope.emit("changed", {"v": 1}, window=ctx.window)

# 或直接用窗口（完整事件名）
await self._window.emit("greeter.changed", {"v": 1})
```

## 权限链

每个 `Scope` / `ScopePermission` 节点带 `allow` / `deny` 模式列表（`*` 通配，匹配相对路径）：

```python
from lumiview.scope import Scope, ScopePermission

root = Scope(
    "app",
    permissions=ScopePermission(allow=("greeter.*",)),   # 只放行 greeter 子树
)

plugin_scope = Scope(
    "greeter",
    permissions=ScopePermission(deny=("greeter.private",)),  # 单个命令拒绝
)
```

规则：

- `deny` 优先；`allow` 为空 = 纯黑名单（不限制）。
- 权限链从命令所在节点向上逐层检查（相对路径）；某层无规则则跳过；**整条链都没有任何规则时默认拒绝**（安全默认）。
- 运行期追加：`scope.allow("x.*")` / `scope.deny("y")`。

## `include()` 纯挂载

`include` 只是把子树挂进父节点（重写父指针），不复制、不合并、不改动被挂载树：

```python
shared = Scope("fs", permissions=ScopePermission(allow=("read.*",)))
root.include(shared)
```

约束：被挂载的实例**只能挂载一次**；未命名 `Scope` 不能挂载；不能挂到自己子树下。

## 简化示例：注入脚本 + 自定义标题栏

完整参考实现见 `python/lumiview/plugins/window_controls.py`（内置的 `WindowControls`）。最小骨架：

```python
from lumiview import Bridge, BridgeContext, Window, WindowOptions
from lumiview.scope import InitContext, Plugin

API_SCRIPT = """
(() => {
  const lumiview = window.lumiview || (window.lumiview = {});
  lumiview.myPlugin = {
    ping() { return lumiview.invoke("myp.ping", {}); },
  };
})();
"""


class MyPlugin(Plugin):
    def __init__(self):
        super().__init__("myp")
        self.command(self.ping)

    def on_init(self, ctx: InitContext) -> InitContext:
        ctx.inject_script += API_SCRIPT
        return ctx

    def ping(self, ctx: BridgeContext) -> str:
        return "pong"


bridge = Bridge(includes=[MyPlugin()])


async def main():
    win = await Window.create(WindowOptions(
        html="<script>window.lumiview.myPlugin.ping().then(console.log)</script>",
        bridge=bridge,
    ))
```

> 提示：无边框窗口（`decorations=False`）配合 `win.start_dragging()` / `win.start_resize_dragging(direction)` 实现自定义标题栏拖动；`WindowControls` 插件已封装好这套交互。
