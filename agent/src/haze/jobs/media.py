"""Reading facts about a media file, without decoding it.

Lives here rather than inside a runtime because two runtimes need it: ffmpeg
uses duration to turn progress into a real fraction, and both ffmpeg and
whisper use it to estimate how much compute a job is before it is placed. The
alternative was whisper importing a private helper out of the ffmpeg runtime,
which is a worse dependency than a module of its own.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PROBE_TIMEOUT_S = 15.0


def duration_seconds(path: Path) -> float | None:
    """Media duration via ffprobe.

    Returns None when ffprobe is absent or the file has no duration -- a
    progress parser then reports frames and rate but no percentage, and a work
    estimate falls back to its default. Both are honest; a guessed duration
    would not be.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 -- resolved path, fixed argv
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=PROBE_TIMEOUT_S, check=False,
        )
        return float(result.stdout.decode().strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def duration_of_named(name: object, inputs: list[Path]) -> float | None:
    """Duration of the input a job's arguments named, matched by file name.

    Placement happens before a job's files are staged, so a runtime cannot
    resolve its input inside a job directory the way ``prepare`` does. It
    matches the name it was given against the files the submitter is sending
    instead, and gets None when there is no match -- an argument error for
    ``prepare`` to explain, not for a work estimate to guess around.
    """
    if not isinstance(name, str):
        return None
    for path in inputs:
        if path.name == name:
            return duration_seconds(path)
    return None
