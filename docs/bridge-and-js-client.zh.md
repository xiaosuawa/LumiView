# JS ↔ Python 通信（Bridge 与客户端）

LumiView 提供双工通信机制：
- **请求/响应（RPC）**：JS 调用 `window.__LUMIVIEW__.invoke(command, payload)`，异步接收 Python 返回值或结构化错误 `BridgeError`。
- **单向事件通知**：
  - Python → JS：`await win.emit(event, payload)`，JS 侧通过 `window.__LUMIVIEW__.listen(event, handler)` 接收。
  - JS → Python：`window.__LUMIVIEW__.emit(event, payload)`，Python 侧通过 `WindowEvent.JsEvent` 接收。

---

## Python 侧：注册命令与错误处理

使用 `Bridge` 注册函数供页面调用，支持普通同步函数（在线程池运行）与异步协程函数（在 asyncio 线程运行）：

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
    """参数根据函数签名自动从 JS payload 解包，支持默认值与 dataclass。"""
    return f"Hello, {name}! " * count


@bridge.command
async def save_user(ctx: BridgeContext, user: UserInfo) -> dict:
    """声明类型为 BridgeContext 的参数会由系统自动注入，无需 JS 传入。"""
    await asyncio.sleep(0.1)
    # ctx.window: 发起调用的 Window
    # ctx.command: 完整命令名（如 "save_user"）
    # ctx.scope: 注册该命令的 Scope 节点
    # ctx.payload: 原始字典
    await ctx.window.set_title(f"Saved: {user.name}")
    return {"ok": True, "user": user.name}


@bridge.command
def check_auth(token: str) -> None:
    if token != "secret":
        # 抛出 BridgeError 会结构化返回给 JS 的 Promise.reject
        raise BridgeError(code="unauthorized", message="Token 无效", data={"retry": False})
```

### 参数绑定与严格类型校验（`cattrs`）

命令参数通过 `cattrs` 进行**严格类型解析**（不进行隐式弱类型转换）：
- **禁止隐式强转**：`bool` 不会作为 `int` 或 `float` 传入，字符串 `"123"` 不会转为 `int`；仅整型数值的浮点数（如 `3.0`）允许匹配 `int`。
- **禁止 `*args` 与 `**kwargs`**：命令签名必须是确定参数。
- **`strict=True`（默认）**：如果 JS 传来的 `payload` 中包含函数签名中不存在的多余字段（即便是零参数命令或仅接收 `BridgeContext` 的命令），都会直接拒绝并返回 `invalid_argument` 错误。需要透传任意字段时可设 `@bridge.command(strict=False)`。
- **支持复杂类型**：支持 `dataclass`、`list[T]`、`dict[K, V]`、可选类型等所有 `cattrs` 可结构化的类型标注。

---

## JS 侧：注入全局对象 `window.__LUMIVIEW__`

除非设置了 `WindowOptions(untrusted=True)`，否则页面在文档起始阶段会自动注入只读锁定的 `window.__LUMIVIEW__` 对象（不可枚举、不可覆写）。

```html
<script>
  const lv = window.__LUMIVIEW__;

  // 1. 调用 Python 命令
  async function run() {
    try {
      const msg = await lv.invoke("greet", { name: "LumiView", count: 2 });
      console.log(msg);
    } catch (err) {
      if (err instanceof lv.BridgeError) {
        console.error(`错误码=${err.code}, 信息=${err.message}`, err.data);
      }
    }
  }

  // 2. 监听 Python 主动推送的事件（返回取消订阅函数）
  const unlisten = lv.listen("app.status", (payload) => {
    console.log("收到状态:", payload);
  });

  // 也兼容标准 EventTarget 接口（payload 位于 event.detail）
  lv.addEventListener("app.status", (e) => console.log(e.detail));

  // 3. 向 Python 发送 fire-and-forget 事件（触发 WindowEvent.JsEvent）
  lv.emit("ui.ready", { theme: "dark" });
</script>
```

客户端内置属性：
- `window.__LUMIVIEW__.v`：通信协议版本（当前为 `1`）
- `window.__LUMIVIEW__.build`：构建自哪一版 LumiView（如 `"0.2.0rc1"`）
- `window.__LUMIVIEW__.plugins`：插件注入的前端命名空间（如 `plugins.window`）
- `window.__LUMIVIEW__.BridgeError`：异常构造器，供 `instanceof` 判断

---

## 前端工程化：TypeScript 类型化门面（`js/`）

如果你的前端使用 Vite / Webpack / TypeScript 构建，仓库 `js/` 目录下提供了一个薄封装层（当前尚未发布到 npm，可本地构建/引用 `js/dist`），它直接复用页面中注入的 `window.__LUMIVIEW__`，不会创建第二个客户端实例：

```ts
import { invoke, listen, emit, isBridgeError } from "lumiview";
import { windowControls } from "lumiview/window-controls";

// 通过声明合并为命令补全端到端类型检查
declare module "lumiview" {
  interface Commands {
    "greet": { payload: { name: string; count?: number }; result: string };
  }
}

const text = await invoke("greet", { name: "TypeScript" }); // 推导为 Promise<string>
const wc = windowControls();                                // 默认对应 "window" 挂载路径
await wc.minimize();
```

---

## 安全与隔离模式

| 配置方式 | 效果 |
|---|---|
| `WindowOptions(bridge=my_bridge)` | 注入 JS 客户端，只允许调用 `my_bridge` 中挂载且通过权限链校验的命令 |
| `WindowOptions(bridge=None)`（默认） | 注入 JS 客户端，但内置空的默认 `Bridge()`，**任何 `invoke` 均返回 `unknown_command`**；仍可使用 `emit` / `listen` |
| `WindowOptions(untrusted=True)` | **不注入任何客户端脚本**（`window.__LUMIVIEW__` 不存在），不能与 `bridge=` 混用，适合加载不可信第三方网页。若页面调用底层 `window.ipc.postMessage(...)`，仅触发 `WindowEvent.WebMessageReceivedEvent` |
