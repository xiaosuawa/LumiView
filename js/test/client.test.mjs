import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

// Built by `npm run build` (dist/inject.iife.js). Keeps the page-side client
// testable without a WebView: the tests only need `window.ipc`, EventTarget
// and CustomEvent.
const SCRIPT = readFileSync(
  new URL("../dist/inject.iife.js", import.meta.url),
  "utf8",
);

function boot() {
  const posted = [];
  const window = {
    ipc: { postMessage: (raw) => posted.push(JSON.parse(raw)) },
  };
  const context = vm.createContext({ window, console, CustomEvent, EventTarget });
  vm.runInContext(SCRIPT, context, { filename: "inject.iife.js" });
  return { window, posted, context, client: window.__LUMIVIEW__ };
}

test("installs a non-enumerable, non-writable client", () => {
  const { window, client } = boot();

  assert.equal(typeof client, "object");
  assert.equal(client.v, 1);
  assert.match(client.build, /^\d+\.\d+\.\d+/);

  // Hidden from enumeration but reachable by name.
  assert.deepEqual(Object.keys(window), ["ipc"]);
  const descriptor = Object.getOwnPropertyDescriptor(window, "__LUMIVIEW__");
  assert.equal(descriptor.enumerable, false);
  assert.equal(descriptor.writable, false);
  assert.equal(descriptor.configurable, false);
});

test("invoke posts the wire message and resolves via dispatch", async () => {
  const { client, posted } = boot();

  const call = client.invoke("greeter.greet", { name: "LumiView" });
  assert.deepEqual(posted, [
    {
      v: 1,
      type: "invoke",
      id: "1",
      command: "greeter.greet",
      payload: { name: "LumiView" },
    },
  ]);

  client.dispatch({ type: "resolve", id: "1", value: "hi" });
  assert.equal(await call, "hi");
});

test("rejections carry code and data", async () => {
  const { client } = boot();

  const call = client.invoke("admin.shutdown");
  client.dispatch({
    type: "reject",
    id: "1",
    error: { code: "forbidden", message: "not allowed", data: { scope: "admin" } },
  });

  await assert.rejects(call, (error) => {
    assert.equal(error.name, "BridgeError");
    assert.equal(error.code, "forbidden");
    assert.equal(error.message, "not allowed");
    assert.deepEqual(error.data, { scope: "admin" });
    return true;
  });
});

test("listen subscribes, delivers detail and unsubscribes", () => {
  const { client } = boot();
  const seen = [];

  const unlisten = client.listen("data.changed", (payload) => seen.push(payload));
  client.dispatch({ type: "event", event: "data.changed", payload: { n: 1 } });
  unlisten();
  client.dispatch({ type: "event", event: "data.changed", payload: { n: 2 } });

  assert.deepEqual(seen, [{ n: 1 }]);
});

test("core methods are read-only and the client stays extensible", () => {
  const { window, client, context } = boot();

  // Test modules are strict mode, so assigning to a non-writable property throws.
  assert.throws(() => {
    client.dispatch = null;
  }, TypeError);
  assert.equal(typeof client.dispatch, "function");

  // Plugins register namespaces under `plugins` (the client is not frozen).
  client.plugins.window = { minimize: () => {} };
  assert.equal(typeof client.plugins.window.minimize, "function");

  // Re-running the script must adopt the existing client, never replace it.
  vm.runInContext(SCRIPT, context, { filename: "inject.iife.js" });
  assert.equal(window.__LUMIVIEW__, client);
});

test("npm facade rejects (not throws) when the client is missing", async () => {
  const facade = await import("../dist/index.mjs");

  assert.equal(facade.isLumiView(), false);
  assert.throws(() => facade.getClient(), /not running inside a LumiView window/);

  // Promise-returning entry points must fail as rejections, not sync throws.
  await assert.rejects(facade.invoke("ping"), /not running inside a LumiView window/);
  await assert.rejects(facade.invokeAs("ping"), /not running inside a LumiView window/);
});

test("windowControls() maps to scoped commands", async () => {
  const calls = [];
  const listened = [];
  globalThis.__LUMIVIEW__ = {
    v: 1,
    build: "test",
    invoke: (command, payload) => {
      calls.push([command, payload]);
      return Promise.resolve(true);
    },
    listen: (event) => {
      listened.push(event);
      return () => {};
    },
  };

  try {
    const { windowControls } = await import("../dist/window-controls.mjs");

    const wc = windowControls("titlebar");
    await wc.minimize();
    await wc.toggleMaximize();
    await wc.startResizeDragging("south-east");
    wc.onMaximizedChange(() => {});

    assert.deepEqual(calls, [
      ["titlebar.minimize", {}],
      ["titlebar.toggle_maximize", {}],
      ["titlebar.start_resize_dragging", { direction: "south-east" }],
    ]);
    assert.deepEqual(listened, ["titlebar.maximized-changed"]);

    // Default scope matches `WindowControls()`.
    const defaultWc = windowControls();
    await defaultWc.close();
    assert.equal(calls[3][0], "window.close");
  } finally {
    delete globalThis.__LUMIVIEW__;
  }
});
