# lumiview

Typed client for the [LumiView](https://github.com/xiaosuawa/LumiView) JavaScript
<-> Python bridge.

LumiView injects `window.__LUMIVIEW__` into every page it hosts. This package is a
thin, typed facade over that object — it never creates a second client, so pending
calls and listeners always live in one place.

```bash
npm install lumiview
```

```ts
import { invoke, listen } from "lumiview";

const unlisten = listen("greeter.changed", (payload) => console.log(payload));
const greeting = await invoke("greeter.greet", { name: "LumiView" });
```

Commands are typed end-to-end by augmenting the `Commands` interface:

```ts
declare module "lumiview" {
  interface Commands {
    "greeter.greet": { payload: { name?: string }; result: string };
  }
}

await invoke("greeter.greet", { name: "x" }); // Promise<string>
await invoke("greeter.greet", { name: 1 });   // type error
```

The built-in `WindowControls` plugin ships a typed subpath too:

```ts
import { windowControls } from "lumiview/window-controls";

const wc = windowControls();          // or windowControls("titlebar")
await wc.minimize();
```

## Without a bundler

You do not need this package. The injected global is always available:

```js
await window.__LUMIVIEW__.invoke("greeter.greet", { name: "x" });
```

## Notes

- **Alpha.** The API is functional but may still change between 0.x releases.
- The client only works inside a LumiView window. Outside one (or with
  `WindowOptions(untrusted=True)`), `invoke()` rejects with an explanatory error
  and `isLumiView()` returns `false`.
- Full documentation: [JS ↔ Python Communication](https://github.com/xiaosuawa/LumiView/blob/main/docs/bridge-and-js-client.md)
  · [Plugins & Permissions](https://github.com/xiaosuawa/LumiView/blob/main/docs/plugins-and-permissions.md).

Licensed under MPL-2.0.
