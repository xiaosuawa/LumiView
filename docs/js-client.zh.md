# JS 客户端

桥的页面侧只有一个全局对象：`window.__LUMIVIEW__`。运行时在 document-start
注入它，早于页面上的任何脚本。

| 成员 | 说明 |
|---|---|
| `invoke(command, payload?)` | 调用 Python 命令，返回 `Promise` |
| `emit(event, payload?)` | 单向事件到 Python（`WindowEvent.JsEvent`） |
| `listen(event, handler, options?)` | 订阅 Python 推送，返回取消函数 |
| `addEventListener` / `removeEventListener` | 底层 `EventTarget`（与 DOM 事件隔离） |
| `dispatch(message)` | Python → 页面的唯一入口，由运行时调用 |
| `plugins` | 注入插件的命名空间容器（如 `plugins.window`） |
| `v` / `build` | 协议版本 / 注入它的 LumiView 版本 |
| `BridgeError` | `invoke()` 失败时使用的错误类 |

这个全局对象用 `Object.defineProperty` 安装：不可枚举（`Object.keys(window)` 看不到）、
不可替换，核心方法只读，页面代码无法劫持 `dispatch`。对象本身保持可扩展——
插件往 `plugins` 下挂自己的命名空间。

## 不打包前端

```html
<script>
  const { invoke, listen } = window.__LUMIVIEW__;

  const unlisten = listen("greeter.changed", (payload) => {
    console.log(payload);
  });

  const greeting = await invoke("greeter.greet", { name: "LumiView" });
</script>
```

`emit()` 是 fire-and-forget，Python 侧收到的是 `WindowEvent.JsEvent`：

```python
from lumiview import WindowEvent

@win.on(WindowEvent.JsEvent, where=lambda e: e.event == "form.submitted")
async def on_submitted(event):
    print(event.payload)
```

`emit()` 不走权限链——它是通知，不是命令。请把 `JsEvent` 的 payload 当作不可信的
页面输入，在 handler 里自行校验。`untrusted=True` 的窗口根本拿不到客户端，也就无法 emit。

## 用打包器：npm 包

```bash
npm install lumiview
```

```ts
import { invoke, listen } from "lumiview";
```

这个包是已安装客户端的**类型化门面**：它不会创建第二个客户端，pending 调用和
监听器始终只有一份。页面不在 LumiView 窗口里（或窗口用了 `untrusted=True`）时，
`invoke()` 会立刻 reject 并给出说明。

### 给命令加类型

声明一次命令表，`invoke()` 就有了端到端的类型：

```ts
declare module "lumiview" {
  interface Commands {
    "greeter.greet": { payload: { name?: string }; result: string };
    "counter.get": { result: number };
  }
}

const greeting = await invoke("greeter.greet", { name: "x" }); // string
const count = await invoke("counter.get");                     // number

// @ts-expect-error —— name 必须是 string
await invoke("greeter.greet", { name: 1 });
```

没声明的命令照样能调，但 payload 和结果都是 `unknown`：

```ts
const raw = await invoke("debug.dump");        // Promise<unknown>

import { invokeAs } from "lumiview";
const pinned = await invokeAs<number>("debug.dump");
```

### 辅助函数

| 导出 | 用途 |
|---|---|
| `isLumiView()` | 页面是否跑在带客户端的 LumiView 窗口里 |
| `getClient()` | 拿到原始的 `window.__LUMIVIEW__`（缺失时抛错） |
| `protocol()` | 注入客户端报告的协议版本 |
| `build()` | 注入客户端的 LumiView 版本 |
| `isBridgeError(error)` | 收窄带 `code` / `data` 的错误类型 |

判断环境请用 `isLumiView()`，不要嗅探 user agent。

## 错误

Python 命令抛 `BridgeError(code, message, data)` 时，`Promise` 会以 `name` 为
`"BridgeError"`、带 `code` / `data` 的 `Error` reject：

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

其余失败（未知命令、权限拒绝、Python 未捕获异常）形状相同，`code` 可能是
`unknown_command`、`forbidden`、`invalid_argument` 或 `internal_error`。

## 线上协议

`invoke` / `emit` 走 wry 的 `window.ipc.postMessage`（页面 → Python）；
Python → 页面走 `eval_js`，唯一入口是 `dispatch()`。

| 方向 | 消息 |
|---|---|
| 页面 → Python | `{v: 1, type: "invoke", id, command, payload}` |
| 页面 → Python | `{v: 1, type: "emit", event, payload}` |
| Python → 页面 | `{type: "resolve", id, value}` |
| Python → 页面 | `{type: "reject", id, error: {code, message, data?}}` |
| Python → 页面 | `{type: "event", event, payload}` |

请求 id 是每个客户端自增的字符串（`"1"`、`"2"`……）。这套形状是公开契约：
注入的客户端和 npm 包一起发版，`v` / `build` 用来发现版本错配。如果 `v` 不是
Python 运行时所说的协议版本，或 `build` 与 Python 包版本不一致，说明页面与运行时
不匹配：重新构建注入客户端（`npm --prefix js run build`），或安装匹配版本的
`lumiview` npm 包。

## `untrusted=True`

`WindowOptions(untrusted=True)` 同时是两个开关：不注入任何东西，**并且**不解析桥消息。
这样的窗口里：

- `typeof window.__LUMIVIEW__ === "undefined"`；
- 所有 `window.ipc.postMessage(...)` 只作为 `WindowEvent.WebMessageReceivedEvent` 出现；
- `Window.emit()` 返回失败的 `Task`。

给不信任的页面用。其它情况都建议保留客户端。

## 插件命名空间

Python 侧注入的插件把 JS API 挂在 `plugins` 下，键名就是挂载名——客户端对象本身
只承载核心成员：

```js
// WindowControls 的默认挂载
await window.__LUMIVIEW__.plugins.window.minimize();

// WindowControls(name="titlebar") 挂载的实例
await window.__LUMIVIEW__.plugins.titlebar.close();
```

内置的 `WindowControls` 还提供类型化的 npm 子路径，直接调用插件命令（不依赖全局）：

```ts
import { windowControls } from "lumiview/window-controls";

const wc = windowControls();            // 或 windowControls("titlebar")
await wc.minimize();
const unlisten = wc.onMaximizedChange((maximized) => console.log(maximized));
```

拖动区域是声明式的，所以只有按钮需要调用 API：

```html
<header data-lumiview-drag-region>
  <span>My App</span>
  <button onclick="__LUMIVIEW__.plugins.window.close()">×</button>
</header>
```

完整标题栏示例见 [plugins.zh.md](plugins.zh.md#windowcontrols)。

## 构建客户端（仓库开发者）

客户端源码在 `js/src`（TypeScript），构建出两个产物：

```bash
npm --prefix js install
npm --prefix js run build    # js/dist/* + python/lumiview/_bridge_client.py
```

生成的 `python/lumiview/_bridge_client.py` 不入库，但运行时必须有；缺了它
`Window.create` 会抛一个提示你去构建的 `RuntimeError`。CI 在构建 wheel 和 sdist
前跑同一条命令，`npm --prefix js test` 用 Node 的 test runner 跑客户端测试。
