"""Thread-safety regressions that also reproduce on GIL-enabled builds."""

from __future__ import annotations

import sys
import threading
import time

from lumiview import App
from lumiview.menu import MenuItem
from lumiview.scope import Scope, iter_tree


def _app() -> App:
    try:
        return App.get()
    except RuntimeError:
        return App(name="thread-safety-tests")


def test_iter_tree_snapshot_survives_concurrent_insert():
    """iter_tree must not raise when another thread mounts a child scope."""
    root = Scope()
    errors: list[BaseException] = []
    stop = threading.Event()
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:

        def reader() -> None:
            while not stop.is_set():
                try:
                    for _node in iter_tree(root):
                        pass
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    return

        def writer() -> None:
            i = 0
            while not stop.is_set():
                root.scope(f"s{i}")
                i += 1

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=writer))
        for thread in threads:
            thread.start()
        time.sleep(0.5)
        stop.set()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(old_interval)

    assert not errors, errors


def test_menu_native_call_reads_inner_once():
    """A concurrent shutdown clearing _inner must not tear the lookup."""
    _app()
    reads = {"n": 0}

    class Inner:
        def set_text(self, text: str) -> None:
            return None

    class TornItem(MenuItem):
        def __getattribute__(self, name: str):
            if name == "_inner":
                reads["n"] += 1
                if reads["n"] == 2:
                    return None
            return super().__getattribute__(name)

    item = TornItem(text="x", id="x")
    item._inner = Inner()  # type: ignore[assignment]

    handle = item.set_text("y")

    assert reads["n"] == 1
    assert handle.done()
