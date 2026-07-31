"""
multi_window.py — Multiple windows sharing a WebContext.

Shows:
  - Shared WebContext — cookies, cache, storage shared across windows
  - Cookie read/write across windows
  - Multiple Window.create() calls

Run:
    python examples/multi_window.py
"""

import asyncio
import tempfile

from wryview import WebContext

from lumiview import App, Window

app = App(name="MultiWindowDemo", exit_on_last_window=True)

# ── Shared data directory — all windows share cookies/cache ───────────────────

SHARED_DIR = tempfile.mkdtemp(prefix="lumiview_multi_")
CTX = WebContext(data_directory=SHARED_DIR)


async def main():
    print(f"Shared data dir: {SHARED_DIR}")

    # Window A — sets a cookie
    win_a = await Window.create(
        title="Multi-Window — A",
        url="https://example.com",
        width=700,
        height=500,
        web_context=CTX,
    )

    # Window B — shares the same WebContext
    win_b = await Window.create(
        title="Multi-Window — B",
        url="https://example.com",
        width=700,
        height=500,
        web_context=CTX,
    )

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
