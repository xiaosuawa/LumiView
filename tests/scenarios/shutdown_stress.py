"""app: ``call_on_main`` from worker threads settles during shutdown.

Regression for the ``_pending`` admission/cleanup race: every handle must
end up resolved or failed with ``AppClosedError`` — never abandoned (which
would block the caller forever) and never raise from the caller thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
import threading

from lumiview import App, AppClosedError


async def _entry() -> None:
    app = App.get()
    stop = threading.Event()
    timeouts: list[int] = []

    def worker() -> None:
        while not stop.is_set():
            handle = app.call_on_main(lambda: None)
            try:
                handle.result(timeout=2.0)
            except AppClosedError:
                return
            except concurrent.futures.TimeoutError:
                timeouts.append(1)
                return
            except Exception:
                pass

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for thread in threads:
        thread.start()

    await asyncio.sleep(0.15)
    app.exit(0)
    # Let the workers observe the closing flag and settle their handles
    # while the main thread is still processing the exit event.
    await asyncio.sleep(0.05)
    stop.set()

    assert not timeouts, f"{len(timeouts)} call_on_main handle(s) never settled"


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)
    code = app.run(_entry)
    sys.exit(code if code is not None else 0)


if __name__ == "__main__":
    sys.exit(main())
