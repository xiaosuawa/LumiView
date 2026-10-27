from __future__ import annotations

import logging
import sys


def init_logging() -> None:
    """Route ``lumiview`` DEBUG logs to stderr.

    The child process's output is captured by ``run_scenario`` and only
    printed when it fails, so a CI failure shows the last lifecycle step
    instead of a bare timeout.
    """

    logger = logging.getLogger("lumiview")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
