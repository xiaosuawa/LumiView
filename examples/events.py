"""
events.py — Events in both directions, plus one-shot waits.

Shows:
  - AppEvent.ReadyEvent / AppEvent.CloseRequestedEvent / AppEvent.ClosedEvent
    (the close hook runs before the windows are released, the closed one
    after everything is gone)
  - WindowEvent.TitleChangedEvent with a cancellable Subscription
  - win.wait_for(...) — one-shot wait for the next matching event
  - WindowEvent.JsEvent — page -> Python notifications via __LUMIVIEW__.emit()
  - win.emit() — Python -> page events via __LUMIVIEW__.listen()
  - WindowEvent.ClosedEvent — fires once after the native window is gone

Run:
    python examples/events.py
"""

import asyncio

from lumiview import App, AppEvent, Window, WindowEvent, WindowOptions

app = App(name="EventsDemo")

HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Events Demo</title></head>
<body style="font-family:sans-serif;padding:2rem;">
  <h2>LumiView Events Demo</h2>
  <button id="ping">Send page.ping to Python</button>
  <pre id="log" style="background:#1e1e2e;color:#cdd6f4;padding:1em;"></pre>
<script>
  const log = document.getElementById('log');
  document.getElementById('ping').onclick = () => {
    window.__LUMIVIEW__.emit('page.ping', {n: Date.now()});
  };
  window.__LUMIVIEW__.listen('py.event', (payload) => {
    log.textContent += `[py.event] ${JSON.stringify(payload)}\n`;
  });
</script>
</body>
</html>"""


# ── App-level events ─────────────────────────────────────────────────────────


@app.on(AppEvent.ReadyEvent)
async def on_ready(event: AppEvent.ReadyEvent):
    print("[AppEvent] Ready — app is running.")


@app.on(AppEvent.CloseRequestedEvent)
async def on_close(event: AppEvent.CloseRequestedEvent):
    # Dispatched before the windows are released: native calls still work.
    for win in app.windows:
        await win.set_title("closing…")
    print("[AppEvent] Close requested — shutting down gracefully.")


@app.on(AppEvent.ClosedEvent)
async def on_closed(event: AppEvent.ClosedEvent):
    # Irreversible: the native side is gone, new work fails.
    print(f"[AppEvent] Closed — exit code {event.exit_code}.")


async def main():
    win = await Window.create(
        WindowOptions(
            title="Events Demo",
            html=HTML,
            width=800,
            height=600,
            devtools=True,
        )
    )
    await win.wait_loaded()

    # ── Window closed ─────────────────────────────────────────────────────

    @win.on(WindowEvent.ClosedEvent)
    async def on_closed(event: WindowEvent.ClosedEvent):
        print("[WindowEvent] Closed — native window is gone.")

    # ── Window-level event + cancellable subscription ─────────────────────

    title_sub = win.on(WindowEvent.TitleChangedEvent)

    @title_sub
    async def on_title_changed(event: WindowEvent.TitleChangedEvent):
        print(f"[WindowEvent] Title changed -> {event.title!r}")

    # Register the one-shot waiter *before* triggering the event.
    title_waiter = win.wait_for(WindowEvent.TitleChangedEvent, timeout=5)
    await win.eval_js("document.title = 'LumiView Events!'")
    event = await title_waiter
    print(f"[wait_for] got {type(event).__name__}: {event.title!r}")

    title_sub.cancel()  # no more title callbacks

    # ── Page -> Python: WindowEvent.JsEvent ───────────────────────────────

    @win.on(WindowEvent.JsEvent, where=lambda e: e.event == "page.ping")
    async def on_ping(event: WindowEvent.JsEvent):
        print(f"[JsEvent] page.ping payload={event.payload!r}")

        # ── Python -> page: __LUMIVIEW__.listen('py.event', ...) ──────────
        await win.emit("py.event", {"reply": "pong", "payload": event.payload})

    # Fire the page button from Python (a user would click it).
    await win.eval_js("document.getElementById('ping').click()")
    await asyncio.sleep(0.5)  # let the JS listener print

    print("App running — close the window or press Ctrl+C.")


if __name__ == "__main__":
    app.run(main)
