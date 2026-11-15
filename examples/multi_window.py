"""
multi_window.py — Multiple windows sharing a WebContext.

Shows:
  - Shared WebContext — cookies, cache, storage shared across windows
  - Cookie read/write across windows
  - Multiple Window.create() calls
  - App.windows / App.get_window / Window.id introspection

Run:
    python examples/multi_window.py
"""

import asyncio
import tempfile

from lumiview import App, WebContext, Window, WindowOptions

app = App(name="MultiWindowDemo", exit_on_last_window=True)

# ── Shared data directory — all windows share cookies/cache ───────────────────

SHARED_DIR = tempfile.mkdtemp(prefix="lumiview_multi_")


async def main():
    print(f"Shared data dir: {SHARED_DIR}")

    # Created on the main thread inside the running app: WebContext.create is
    # @main_thread, and one context is shared by every window below.
    ctx = await WebContext.create(data_directory=SHARED_DIR)

    # Window A — sets a cookie
    win_a = await Window.create(
        WindowOptions(
            title="Multi-Window — A",
            url="https://example.com",
            width=700,
            height=500,
            web_context=ctx,
        )
    )

    # Window B — shares the same WebContext
    win_b = await Window.create(
        WindowOptions(
            title="Multi-Window — B",
            url="https://example.com",
            width=700,
            height=500,
            web_context=ctx,
        )
    )

    # App-level registry — plain reads, safe from the asyncio thread.
    print("open windows:", [w.id for w in app.windows])
    print("lookup by id:", app.get_window(win_a.id) is win_a)

    await asyncio.sleep(0.5)

    # Set a cookie from window A...
    await win_a.set_cookie("shared_key", "hello_from_A", domain="example.com", path="/")
    print("Cookie set from Window A: shared_key=hello_from_A")

    # ...and read it from window B — same WebContext, same cookie jar
    cookies = await win_b.cookies()
    print(f"Cookies visible from Window B: {cookies}")

    print("Both windows share cookies, cache, and storage.")


if __name__ == "__main__":
    app.run(main)
