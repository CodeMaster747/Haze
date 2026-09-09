"""Turning runtime chatter into a progress bar.

ffmpeg and Blender both report progress, in formats that have nothing in common.
Parsing them into one :class:`Progress` is what lets the dashboard show "the
remote machine is 43% through, 142 fps, 2 minutes left" for either.

This is deliberately the feature that shipped instead of interactive
application streaming. Watching frames appear from a remote GPU in real time
carries most of the same weight and costs a hundredth as much -- no capture
APIs, no encoders, no permission prompts, no relay bandwidth.
"""

from __future__ import annotations

import re
import time

from haze.jobs.spec import Progress


class ProgressParser:
    """Feeds output lines in, keeps a running :class:`Progress`."""

    def feed(self, line: str) -> bool:
        """Returns True if the line changed anything worth publishing."""
        raise NotImplementedError

    @property
    def progress(self) -> Progress:
        raise NotImplementedError


class FfmpegProgressParser(ProgressParser):
    """Parses ``ffmpeg -progress pipe:1 -nostats``.

    That flag makes ffmpeg emit newline-delimited ``key=value`` blocks
    terminated by ``progress=continue`` or ``progress=end`` -- a stable,
    machine-readable format, unlike the default status line which is designed
    for a terminal and rewrites itself with carriage returns.
    """

    def __init__(self, total_duration_s: float | None = None) -> None:
        self._total = total_duration_s
        self._p = Progress(stage="encoding")
        self._fields: dict[str, str] = {}

    def feed(self, line: str) -> bool:
        line = line.strip()
        if "=" not in line:
            return False
        key, _, value = line.partition("=")
        self._fields[key] = value

        if key == "frame":
            with_int = _as_int(value)
            if with_int is not None:
                self._p.frames_done = with_int
        elif key == "fps":
            rate = _as_float(value)
            if rate:
                self._p.rate = f"{rate:.0f} fps"
        elif key == "speed":
            # e.g. "3.42x" -- more meaningful than fps for a viewer, because it
            # compares against realtime.
            if value.strip() not in {"", "N/A"}:
                self._p.detail = f"{value.strip()} realtime"
        elif key == "out_time_ms" and self._total:
            # Despite the name ffmpeg reports MICROseconds here. Getting this
            # wrong yields a progress bar that finishes 1000x early.
            micros = _as_int(value)
            if micros is not None:
                seconds = micros / 1_000_000
                self._p.fraction = min(1.0, max(0.0, seconds / self._total))
                if self._p.fraction > 0.01:
                    elapsed_fraction = self._p.fraction
                    remaining = self._total * (1 - elapsed_fraction)
                    speed = _as_float((self._fields.get("speed") or "1x").rstrip("x")) or 1.0
                    self._p.eta_seconds = remaining / speed if speed > 0 else None
        elif key == "progress":
            if value == "end":
                self._p.fraction = 1.0
                self._p.stage = "done"
                self._p.eta_seconds = 0.0
            return True

        return key in {"frame", "fps", "out_time_ms", "speed"}

    @property
    def progress(self) -> Progress:
        return self._p


class BlenderProgressParser(ProgressParser):
    """Parses Blender's headless (``-b``) output.

    Blender changed this format, and the version installed matters. Blender 5.x
    prefixes every line with a timestamp and a category::

        00:00.687  render           | Saved: '/tmp/out/0001.png'
        00:00.412  render           | Fra: 1 | Rendering 8 / 16 samples

    while older releases (and Cycles) emit the flatter form::

        Fra:1 Mem:49.06M (Peak 49.60M) | Time:00:27.91 | Remaining:00:08.10

    Both are handled: the prefix is stripped when present, then the remainder is
    matched. Writing against only the documented older format is precisely the
    mistake that produced a parser passing its unit tests while matching nothing
    a real Blender printed.
    """

    # "00:00.687  render           | " -- timestamp, category, pipe.
    _PREFIX = re.compile(r"^\d{2}:\d{2}\.\d{2,3}\s+\w+\s*\|\s*")

    _SAVED = re.compile(r"Saved:\s*'(.+?)'")
    _RENDERING_FRAME = re.compile(r"Rendering frame (\d+)")
    _ANIMATION_RANGE = re.compile(r"Rendering animation \(frames (\d+)\.\.(\d+)\)")
    _SAMPLES = re.compile(r"Rendering (\d+) / (\d+) samples")
    _FRAME_TIME = re.compile(r"Time:\s*(?:(\d+):)?(\d+):([\d.]+)")

    # Legacy / Cycles flat form.
    _LEGACY_FRA = re.compile(r"^Fra:(\d+)")
    _REMAINING = re.compile(r"Remaining:\s*(?:(\d+):)?(\d+):([\d.]+)")
    _PEAK_MEM = re.compile(r"\(Peak ([\d.]+)([MG])\)")

    def __init__(self, frame_start: int = 1, frame_end: int = 1) -> None:
        self._start = frame_start
        self._end = frame_end
        self._p = Progress(
            stage="rendering",
            frames_done=0,
            frames_total=max(1, frame_end - frame_start + 1),
        )
        self.saved_files: list[str] = []
        self.peak_mem_bytes = 0
        self._frame_seconds: list[float] = []

    def feed(self, line: str) -> bool:
        body = self._PREFIX.sub("", line.strip())
        changed = False

        # Blender states the range it is actually rendering; trust that over
        # the range we asked for, which can differ if the .blend overrides it.
        span = self._ANIMATION_RANGE.search(body)
        if span:
            self._p.frames_total = max(1, int(span.group(2)) - int(span.group(1)) + 1)
            changed = True

        saved = self._SAVED.search(body)
        if saved:
            self.saved_files.append(saved.group(1))
            # Count from Saved, not from "Rendering frame": the latter announces
            # a frame that has *started*, so counting it would report 1/1 done
            # the moment rendering began.
            self._p.frames_done = len(self.saved_files)
            self._p.fraction = min(1.0, len(self.saved_files) / (self._p.frames_total or 1))
            self._p.detail = saved.group(1).rsplit("/", 1)[-1]
            self._estimate_remaining()
            return True

        frame = self._RENDERING_FRAME.search(body)
        if frame:
            self._p.stage = f"frame {frame.group(1)}"
            return True

        # Sample progress gives a smooth bar within a frame rather than one
        # that jumps only when a frame completes.
        samples = self._SAMPLES.search(body)
        if samples:
            done_frames = self._p.frames_done or 0
            total_frames = self._p.frames_total or 1
            within = int(samples.group(1)) / max(1, int(samples.group(2)))
            self._p.fraction = min(1.0, (done_frames + within) / total_frames)
            self._p.detail = f"{samples.group(1)}/{samples.group(2)} samples"
            return True

        elapsed = self._FRAME_TIME.search(body)
        if elapsed and "Saving" in body:
            seconds = _hms(elapsed)
            self._frame_seconds.append(seconds)
            self._p.rate = f"{seconds:.1f}s/frame"
            self._estimate_remaining()
            changed = True

        # --- legacy flat form ------------------------------------------------
        legacy = self._LEGACY_FRA.match(body)
        if legacy:
            mem = self._PEAK_MEM.search(body)
            if mem:
                scale = 1 << 20 if mem.group(2) == "M" else 1 << 30
                self.peak_mem_bytes = max(self.peak_mem_bytes, int(float(mem.group(1)) * scale))

            remaining = self._REMAINING.search(body)
            if remaining:
                per_frame = _hms(remaining)
                left = (self._p.frames_total or 1) - (self._p.frames_done or 0)
                self._p.eta_seconds = per_frame + max(0, left - 1) * per_frame

            self._p.stage = f"frame {legacy.group(1)}"
            return True

        return changed

    def _estimate_remaining(self) -> None:
        """Project from measured frame times, which beats Blender's own
        per-frame estimate for a multi-frame job."""
        if not self._frame_seconds:
            return
        average = sum(self._frame_seconds) / len(self._frame_seconds)
        left = (self._p.frames_total or 1) - (self._p.frames_done or 0)
        self._p.eta_seconds = max(0.0, average * left)

    @property
    def progress(self) -> Progress:
        return self._p


class WhisperProgressParser(ProgressParser):
    """Parses the lines ``haze.jobs.runtimes.whisper``'s worker prints::

        duration 241.30
        processed 12.30s / 241.30s
        segment So the first thing to notice is

    Newline-delimited on purpose. Every whisper CLI worth the name draws a
    carriage-return progress bar instead, and the executor's reader
    (``_pump``) works in whole lines -- a ``\\r`` bar emits none, so the job
    would run to completion showing a bar that never moved. This is the same
    reason ffmpeg is invoked with ``-nostats``.
    """

    _DURATION = re.compile(r"^duration\s+([\d.]+)\s*$")
    _PROCESSED = re.compile(r"^processed\s+([\d.]+)s\s*/\s*([\d.]+)s\s*$")

    def __init__(self) -> None:
        self._p = Progress(stage="transcribing")
        self._total: float | None = None
        self._started = time.monotonic()

    def feed(self, line: str) -> bool:
        body = line.strip()

        duration = self._DURATION.match(body)
        if duration:
            # Announced before the first segment, so the UI has a total during
            # the long silence while the model loads.
            self._total = float(duration.group(1)) or None
            if self._total:
                self._p.frames_total = int(self._total)
            return True

        processed = self._PROCESSED.match(body)
        if processed:
            done = float(processed.group(1))
            total = float(processed.group(2)) or self._total
            self._p.frames_done = int(done)
            if total:
                self._total = total
                self._p.frames_total = int(total)
                self._p.fraction = min(1.0, max(0.0, done / total))
            # Audio seconds per wall second -- the natural throughput number for
            # transcription, and comparable across machines the way "142 fps" is
            # for a render.
            elapsed = time.monotonic() - self._started
            if elapsed > 0 and done > 0:
                speed = done / elapsed
                self._p.rate = f"{speed:.1f}x realtime"
                if total:
                    self._p.eta_seconds = max(0.0, (total - done) / speed)
            return True

        if body.startswith("segment "):
            # The transcript arriving live, which is this runtime's equivalent of
            # watching frames appear.
            self._p.detail = body.removeprefix("segment ").strip()[:120]
            return True

        if body == "done":
            self._p.fraction = 1.0
            self._p.stage = "done"
            self._p.eta_seconds = 0.0
            return True

        return False

    @property
    def progress(self) -> Progress:
        return self._p


class NullProgressParser(ProgressParser):
    """For runtimes that report nothing useful. Keeps the last line as detail
    so the UI still shows signs of life."""

    def __init__(self, stage: str = "running") -> None:
        self._p = Progress(stage=stage)

    def feed(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        self._p.detail = stripped[:120]
        return True

    @property
    def progress(self) -> Progress:
        return self._p


def _as_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def _as_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def _hms(match: re.Match[str]) -> float:
    hours = float(match.group(1) or 0)
    return hours * 3600 + float(match.group(2)) * 60 + float(match.group(3))
