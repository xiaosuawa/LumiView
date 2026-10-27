from __future__ import annotations

import logging


def init_logging() -> None:
    logging.getLogger("lumiview").setLevel(logging.DEBUG)
