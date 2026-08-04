"""
events.py — App and Window events, plus Python-to-JS event emission.

Shows:
  - AppEvent.ReadyEvent — fires once when the app is ready
  - AppEvent.AppCloseEvent — fires on graceful shutdown
  - WindowEvent.TitleChangedEvent — fires when the page title changes
  - win.emit() — push events from Python to JS (window.lumiview.listen)

Run:
    python examples/events.py
"""

from lumiview import App, AppEvent, Window, WindowEvent, WindowOptions

app = App(name="EventsDemo")

# ── App-level events ─────────────────────────────────────────────────────────


@app.on(AppEvent.ReadyEvent)
async def on_ready(evt: AppEvent.ReadyEvent):
    print("[AppEvent] Ready — app is running.")


@app.on(AppEvent.AppCloseEvent)
async def on_close(evt: AppEvent.AppCloseEvent):
    print("[AppEvent] Close — shutting down gracefully.")


async def main():
    win = await Window.create(WindowOptions(
        title="Events Demo",
        url="https://www.example.com",
        width=800,
        height=600,
        devtools=True,
    ))

    # ── Window-level event: TitleChanged ────────────────────────────────

    @win.on(WindowEvent.TitleChangedEvent)
    async def on_title_changed(evt: WindowEvent.TitleChangedEvent):
        print(f"[WindowEvent] Title changed → '{evt.title}'")

    # Trigger a title change to fire the hook
    await win.eval_js("document.title = 'LumiView Events!'")

    # ── Push events from Python to JS ───────────────────────────────────

    # Register a JS-side listener
    await win.eval_js(
        "window.lumiview.listen('my.event', (p) => { window.__evt = p.data; });"
    )
    await win.emit("my.event", {"data": "Hello from Python!", "ts": 42})
    print("[emit] Sent 'my.event' to JS.")

    received = await win.eval_js("window.__evt")
    print(f"[emit] JS received payload: {received!r}")

    print("App running — close the window or press Ctrl+C.")


if __name__ == "__main__":
    app.run(main)
