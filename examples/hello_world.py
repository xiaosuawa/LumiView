"""
hello_world.py — Minimal LumiView app.

Creates a window, loads a URL, executes JS, and prints the page title.
The simplest possible starting point.

Run:
    python examples/hello_world.py
"""

import asyncio

# set up logging to see debug output from the app and tasks
# import logging
# logging.basicConfig(level=logging.DEBUG)

from lumiview import App, Window, WindowOptions

app = App(name="HelloWorld")


async def main():
    # Create a window — returns Task[Window], so we await it.
    win = await Window.create(WindowOptions(
        title="Hello LumiView!",
        url="https://example.com",
        width=900,
        height=640,
        devtools=True,
    ))

    # Wait for PageLoadFinishedEvent. wait_loaded() is registered inside
    # create(), so it cannot miss a fast load (create() returns before the
    # page finishes loading).
    await win.wait_loaded()

    # eval_js returns Task[str] — await to get the result.
    title = await win.eval_js("document.title")
    print(f"Page title: {title}")

    await asyncio.sleep(1)  # Wait a bit before loading the next URL

    # load_url is fire-and-forget, no Task needed.
    win.load_url("https://www.python.org")
    print("App running — close the window or press Ctrl+C to exit.")


if __name__ == "__main__":
    app.run(main)
