from __future__ import annotations

import sys

from lumiview import App


async def _entry() -> None:
    raise RuntimeError("boom")


def main() -> int:
    from _harness import init_logging

    init_logging()
    app = App(exit_on_last_window=False)

    code = app.run(_entry)
    assert code == 1, f"expected exit 1, got {code}"
    sys.exit(code)


if __name__ == "__main__":
    sys.exit(main())
