"""
bridge_demo.py — JS ↔ Python IPC via Bridge.

Shows:
  - @bridge.command — expose sync Python functions to JS
    (payload is unpacked by signature; commands no longer receive the raw dict)
  - @bridge.command (async) — expose async Python functions
  - Structured error handling (BridgeError)

JS calls Python via ``window.lumiview.invoke(command, payload)``,
which returns a Promise that resolves with the Python return value.

Run:
    python examples/bridge_demo.py
"""

from lumiview import App, Bridge, BridgeError, Window

app = App(name="BridgeDemo")

b = Bridge()


@b.command
def greet(name: str) -> dict:
    """Say hello — synchronous Python function."""
    return {"msg": f"Hello, {name}!"}


@b.command
async def delayed_greet(name: str) -> dict:
    """Async example — runs on the asyncio loop without blocking."""
    import asyncio

    await asyncio.sleep(1.5)
    return {"msg": f"Hello after delay, {name}!"}


@b.command
def maybe_fail(msg: str) -> None:
    """Raise a structured error — caught and returned to JS."""
    raise BridgeError("demo_error", msg)


HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Bridge Demo</title></head>
<body style="font-family:sans-serif;padding:2rem;">
  <h2>LumiView Bridge Demo</h2>
  <p>Each button calls a Python function via
     <code>window.lumiview.invoke(command, payload)</code>.</p>
  <button onclick="call('greet',{name:'LumiView'})">Greet</button>
  <button onclick="call('delayed_greet',{name:'Async'})">Delayed Greet (1.5s)</button>
  <button onclick="call('maybe_fail',{msg:'demo error'})">Trigger Error</button>
  <pre id="log" style="background:#1e1e2e;color:#cdd6f4;padding:1em;"></pre>
<script>
  const log = document.getElementById('log');

  async function call(cmd, payload) {
    try {
      const t0 = performance.now();
      const result = await window.lumiview.invoke(cmd, payload);
      const ms = (performance.now() - t0).toFixed(0);
      log.textContent += `[OK ${ms}ms] ${cmd} => ${JSON.stringify(result)}\n`;
    } catch (e) {
      log.textContent += `[ERR] ${cmd} => code=${e.code} message=${e.message}\n`;
    }
  }
</script>
</body>
</html>"""


async def main():
    win = await Window.create(
        title="LumiView Bridge Demo",
        html=HTML,
        width=650,
        height=450,
        devtools=True,
        bridge=b,
    )
    print("Bridge ready — click the buttons to call Python from JS.")


if __name__ == "__main__":
    app.run(main)
