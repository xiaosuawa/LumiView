# IPC：命令、Scope 与插件

桥把 Python 函数暴露给页面。一次 JS 调用会经过权限链、按 Python 签名绑定参数、
离开 GUI 线程执行，最后以 `Promise` 回到页面。没有 HTTP 服务器，也没有手写序列化。

## 最小命令

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

- 命令名是 scope 树上的点分路径。注册在根上的命令就叫 `greet`；注册在名为
  `greeter` 的 scope 上则是 `greeter.greet`。
- 返回值会被 JSON 编码后送回页面（无法序列化会得到 `internal_error`）。
- `async def` 命令在 asyncio 线程被 await，普通 `def` 命令走线程池；两者都不在 GUI 线程。

## 参数绑定规则

payload 的键按参数名绑定：

```python
@bridge.command
def search(ctx: BridgeContext, query: str, limit: int = 20) -> list[str]:
    ...
```

- 命令里不能用 `*args` / `**kwargs`，注册时就会抛 `ValueError`。
- 多余的 payload 键默认报错（`invalid_argument`）；注册时 `strict=False` 可放开。
- 缺少必填参数报 `invalid_argument`；类型严格校验（`"3"` 不会被偷偷转成 `3`）。
- `BridgeContext` 是注入参数，不由页面传。字段：`window`、`payload`（原始 payload）、
  `command`（完整命令名）、`scope`（注册节点）。
- 注册选项：`@bridge.command(name="custom", replace=True, strict=False)`。

想给页面返回结构化错误，抛 `BridgeError`：

```python
from lumiview import BridgeError

@bridge.command
def read(path: str) -> str:
    try:
        return open(path).read()
    except FileNotFoundError:
        raise BridgeError("not_found", "No such file", {"path": path})
```

页面拿到的是 `name === "BridgeError"`、`code === "not_found"`、
`data === {"path": ...}` 的 `Error`。

## Scope 与插件

`Scope` 是命令树上的命名节点；`Plugin` 是带窗口生命周期钩子的 `Scope`。

```python
from lumiview import Bridge, BridgeContext, ScopePermission
from lumiview.scope import InitContext, Plugin


class Greeter(Plugin):
    def __init__(self) -> None:
        super().__init__("greeter")
        self.command(self.greet)

    def on_init(self, ctx: InitContext) -> InitContext:
        # 在 tao 窗口 / WebView 创建之前调用：可以追加页面 JS，
        # 也可以在这里注册早期事件 handler。
        ctx.inject_script += "window.__greeterReady = true;"
        return ctx

    def on_ready(self, window) -> None:
        # 每个使用这个 bridge 的窗口创建完成后调用一次。
        print("greeter ready on", window)

    def greet(self, ctx: BridgeContext, name: str = "world") -> str:
        return f"Hello, {name}!"


bridge = Bridge(includes=[Greeter()])
```

- `on_init` 按树顺序对每个插件调用；返回修改后的 `InitContext`（`inject_script`
  会累积）。
- `on_ready` 对每个使用该 bridge 的窗口调用一次。
- `InitContext` 还带 `window`（窗口空壳）和 `options`（正在应用的
  `WindowOptions`）——这是订阅「`Window.create()` 返回之前就触发」的事件的唯一安全位置。

## 权限

每个节点带 `allow` / `deny` 模式列表。模式是 `*` 通配，匹配**相对该节点**的命令路径，
`*` 可以跨过点号。

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

链上的判定规则（从命令节点一路到根）：

- `deny` 优先于 `allow`。
- `allow` 为空表示「不设白名单」，只按黑名单拦。
- 没有规则的节点跳过。
- 整条链都**没有**任何规则时，调用被拒绝——默认安全。
- `Bridge` 根默认 `allow=("*",)`，除非你显式传 `permissions=`。

运行期也能追加：`scope.allow("x.*")`、`scope.deny("x.y")`。

## 挂载共享子树

`Scope.include(other)` 只是把子树挂上去，不复制、不合并。名字和权限都是相对路径，
所以同一棵子树挂到哪里都能正常工作。

```python
from lumiview import Bridge
from lumiview.scope import Scope, ScopePermission

fs = Scope("fs", permissions=ScopePermission(allow=("read.*",)))
bridge = Bridge()
bridge.include(fs)          # 命令变成 fs.read.*
```

约束：scope 必须有名字、只能挂载一次、不能挂到自己的子树下。要换挂载名，构造时直接用它。

## JS 侧

```js
const { invoke, listen } = window.__LUMIVIEW__;

const greeting = await invoke("greeter.greet", { name: "LumiView" });
const unlisten = listen("greeter.changed", (payload) => console.log(payload));
```

插件把自己的 JS API 挂在 `plugins` 下，键名就是挂载名，不污染全局：

```js
const greeter = window.__LUMIVIEW__.plugins.greeter;
```

完整的页面侧参考见 [js-client.zh.md](js-client.zh.md)。

Python 主动推送事件：`window.emit()`（完整事件名），或
`ctx.scope.emit("changed", payload, window=ctx.window)`（自动加 scope 前缀）。

## 运行期行为

- `Window.bridge` 是只读 getter，随窗口生命周期存在。需要扩展命令时直接在它上面注册
  （`win.bridge.command(...)`）；不支持整棵替换——注入的客户端和插件的
  `on_init` / `on_ready` 属于创建窗口时的那棵树。
- `bridge=None` 仍然注入客户端（`emit()` / `listen()` 可用），但所有 `invoke()`
  都以 `unknown_command` 失败。
- `WindowOptions(untrusted=True)` 什么都不注入，**并且**不解析 IPC 消息；原始消息
  以 `WindowEvent.WebMessageReceivedEvent` 出现，`win.bridge` 为 `None`。

## WindowControls

内置的 `WindowControls` 插件提供自定义标题栏 API、声明式拖动区域，以及
最大化/全屏状态同步：

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

- `data-lumiview-drag-region` 标记拖动区域，不用写 JS；
  `data-lumiview-resize-region="east"`（等方向）标记窗口内部的大小调整手柄。
- 按钮直接调用 JS API，它在 `__LUMIVIEW__.plugins.<挂载名>`：默认挂载下是
  `plugins.window.minimize()`；`WindowControls(name="titlebar")` 时命令变成
  `titlebar.*`，API 是 `plugins.titlebar`。

  | JS API | Bridge 命令 | 返回 |
  |---|---|---|
  | `minimize()` | `window.minimize` | — |
  | `toggleMaximize()` | `window.toggle_maximize` | `bool` |
  | `isMaximized()` | `window.is_maximized` | `bool` |
  | `close()` | `window.close` | — |
  | `startDragging()` | `window.start_dragging` | — |
  | `startResizeDragging(direction)` | `window.start_resize_dragging` | — |
  | `onMaximizedChange(fn)` | 监听 `window.maximized-changed` | 退订函数 |

- 打包前端可以不用全局，改用类型化模块：

  ```ts
  import { windowControls } from "lumiview/window-controls";

  const wc = windowControls();          // 或 windowControls("titlebar")
  await wc.minimize();
  const unlisten = wc.onMaximizedChange((maximized) => console.log(maximized));
  ```

- 窗口边缘缩放是原生的（Windows 上走 WM_NCHITTEST，其它平台由 tao 处理），
  不要用 resize region 盖住边框。
- `WindowControls(name="x", drag_regions=False, link_fullscreen=False,
  link_maximized=False)` 可以关掉不需要的部分。拖动/全屏钩子每页只安装一次
  （第一个实例生效）；额外实例通过各自的 JS API 控制。
