"""
events.py — App and Window hook events, plus Python-to-JS event emission.

Shows:
  - AppHookEvent.Ready — fires once when the app is ready
  - AppHookEvent.Close — fires on graceful shutdown
  - WindowHookEvent.TitleChanged — fires when the page title changes
  - win.emit() — push events from Python to JS (window.lumiview.listen)

Run:
    python examples/events.py
"""

import asyncio

from lumiview import App, AppHookEvent, Window, WindowHookEvent

app = App(name="EventsDemo")

# ── App-level hooks ───────────────────────────────────────────────────────────


@app.on(AppHookEvent.Ready)
async def on_ready():
    print("[AppHook] Ready — app is running.")


@app.on(AppHookEvent.Close)
async def on_close():
    print("[AppHook] Close — shutting down gracefully.")


async def main():
    win = await Window.create(
        title="Events Demo",
        url="https://www.example.com",
        width=800,
        height=600,
        devtools=True,
    )

    # ── Window-level hook: TitleChanged ──────────────────────────────────

    @win.on(WindowHookEvent.TitleChanged)
    async def on_title_changed(title: str):
        print(f"[WindowHook] Title changed → '{title}'")

    # Trigger a title change to fire the hook
    await win.eval_js("document.title = 'LumiView Events!'")

    # ── Push events from Python to JS ───────────────────────────────────

    await asyncio.sleep(1)
    await win.emit("my.event", {"data": "Hello from Python!", "ts": 42})
    print("[emit] Sent 'my.event' to JS.")

    # On the JS side, listen with:
    #   window.lumiview.listen('my.event', (payload) => console.log(payload));

    print("App running — close the window or press Ctrl+C.")


if __name__ == "__main__":
    app.run(main)
