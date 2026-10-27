from __future__ import annotations

import sys

from lumiview import App


def main() -> int:
    # App.get() before any App() exists must raise.
    try:
        App.get()
    except RuntimeError:
        pass
    else:
        raise AssertionError("App.get() did not raise before any App() was created")

    # First instance succeeds.
    App(exit_on_last_window=False)

    # Second instance must raise (hard singleton).
    try:
        App(exit_on_last_window=False)
    except RuntimeError:
        pass
    else:
        raise AssertionError("second App() did not raise")

    return 0


if __name__ == "__main__":
    sys.exit(main())
