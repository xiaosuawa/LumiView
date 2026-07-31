"""
hello_world_sync.py — Minimal LumiView app with synchronous API.

Creates a window, loads a URL, executes JS, and prints the page title.
The simplest possible starting point.

Run:
    python examples/hello_world_sync.py
"""

import time
from lumiview import App, Window

app = App(name="HelloWorld")


def main():
    # Create a window — returns Task[Window], so we await it.
    win = Window.create(
        title="Hello LumiView!",
        url="https://example.com",
        width=900,
        height=640,
        devtools=True,
    ).result()

    # eval_js returns Task[str] — await to get the result.
    title = win.eval_js("document.title").result()
    print(f"Page title: {title}")
    
    time.sleep(1)  # Wait a bit before loading the next URL

    # load_url is fire-and-forget, no Task needed.
    win.load_url("https://www.python.org")
    print("App running — close the window or press Ctrl+C to exit.")


if __name__ == "__main__":
    app.run(main)
