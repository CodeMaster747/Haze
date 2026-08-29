"""Logging setup.

Deliberately plain stdlib logging.  The agent runs on the user's own laptop and
its logs are read by a human in a terminal, not shipped to an aggregator, so
structured JSON output would cost readability for a benefit nobody collects.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup(verbose: bool = False) -> None:
    """Configure root logging.  Idempotent -- devnet calls this per subprocess."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = logging.DEBUG if verbose or os.environ.get("HAZE_DEBUG") else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s", datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # uvicorn installs its own handlers and would otherwise double every line.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True

    # zeroconf is chatty at DEBUG about every unrelated device on the network.
    logging.getLogger("zeroconf").setLevel(logging.WARNING)

    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"haze.{name}")
