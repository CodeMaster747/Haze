"""A CPU-bound benchmark that needs nothing installed.

Exists so `haze bench` works on any machine, and so the first job anyone runs
cannot fail because ffmpeg is missing. It is also the fairest speedup
measurement available: identical work, identical code, no codec or driver
differences between nodes.

Run as a module so it goes through the normal subprocess path -- rlimits, the
process group, niceness and the kill timer all apply exactly as they would to
ffmpeg.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Any

from haze.jobs.progress import ProgressParser
from haze.jobs.runtimes.base import JobArgumentError, Prepared, register
from haze.jobs.spec import Progress

CHUNK = 1 << 20        # 1 MiB block
PASSES_PER_ROUND = 32  # ~32 MiB hashed per round

# Sized so a round is tens of milliseconds on a modern core, which makes
# `rounds` a meaningful dial: 200 rounds is a few seconds of real work, and
# the difference between a fast and a slow machine is visible rather than
# lost in process startup.


class _BenchProgressParser(ProgressParser):
    """Reads the ``round=<n>/<total>`` lines the worker prints."""

    def __init__(self, rounds: int) -> None:
        self._p = Progress(stage="hashing", frames_total=rounds, frames_done=0)
        self._rounds = rounds
        self._started = time.monotonic()

    def feed(self, line: str) -> bool:
        line = line.strip()
        if not line.startswith("round="):
            return False
        try:
            done = int(line.removeprefix("round=").split("/")[0])
        except (ValueError, IndexError):
            return False
        self._p.frames_done = done
        self._p.fraction = min(1.0, done / self._rounds)
        elapsed = time.monotonic() - self._started
        if done:
            per_round = elapsed / done
            self._p.eta_seconds = per_round * (self._rounds - done)
            self._p.rate = f"{CHUNK * PASSES_PER_ROUND / per_round / 2**20:.0f} MiB/s"
        return True

    @property
    def progress(self) -> Progress:
        return self._p


class HashBenchRuntime:
    name = "hashbench"
    description = "CPU benchmark — repeated hashing. Needs nothing installed."

    def available(self) -> bool:
        return True

    def prepare(self, args: dict[str, Any], workdir: Path) -> Prepared:
        rounds = args.get("rounds", 200)
        if not isinstance(rounds, int) or not 1 <= rounds <= 100_000:
            raise JobArgumentError("`rounds` must be an integer between 1 and 100000")

        return Prepared(
            argv=[sys.executable, "-m", "haze.jobs.runtimes.hashbench", str(rounds)],
            parser=_BenchProgressParser(rounds),
            cwd=workdir,
        )


register(HashBenchRuntime())


def _worker(rounds: int) -> int:
    """The actual work. Deliberately CPU-bound and allocation-light, so it
    measures compute rather than memory bandwidth or disk."""
    data = bytes(range(256)) * (CHUNK // 256)
    digest = b"haze"
    for index in range(1, rounds + 1):
        for _ in range(PASSES_PER_ROUND):
            digest = hashlib.sha256(digest + data).digest()
        print(f"round={index}/{rounds}", flush=True)
    print(f"digest={digest.hex()}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover -- subprocess entrypoint
    sys.exit(_worker(int(sys.argv[1]) if len(sys.argv) > 1 else 200))


__all__ = ["HashBenchRuntime"]
