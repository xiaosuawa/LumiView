from __future__ import annotations

import sys

from lumiview import App


async def _entry() -> None:
    App.get().exit(0)


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)

    code = app.run(_entry)
    assert code == 0, f"run() returned {code}"

    # A second run() over the same app must raise (state machine is single-shot).
    try:
        app.run(_entry)
    except RuntimeError:
        pass
    else:
        raise AssertionError("second run() did not raise")

    return 0


if __name__ == "__main__":
    sys.exit(main())
