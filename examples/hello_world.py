"""
hello_world.py — Minimal LumiView app.

Creates a window, loads a URL, executes JS, and prints the page title.
The simplest possible starting point.

Run:
    python examples/hello_world.py
"""

import asyncio
from lumiview import App, Window

app = App(name="HelloWorld")


async def main():
    # Create a window — returns Task[Window], so we await it.
    win = await Window.create(
        title="Hello LumiView!",
        url="https://example.com",
        width=900,
        height=640,
        devtools=True,
    )

    # eval_js returns Task[str] — await to get the result.
    title = await win.eval_js("document.title")
    print(f"Page title: {title}")
    
    await asyncio.sleep(1)  # Wait a bit before loading the next URL

    # load_url is fire-and-forget, no Task needed.
    win.load_url("https://www.python.org")
    print("App running — close the window or press Ctrl+C to exit.")


if __name__ == "__main__":
    app.run(main)
