"""Video transcoding.

The encoder is chosen from an allowlist and matched against what this node's
ffmpeg actually reports, so a job asking for NVENC on a machine without it
fails immediately with a clear message rather than after ffmpeg has spent a
minute discovering the same thing.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from haze.jobs import media
from haze.jobs.progress import FfmpegProgressParser
from haze.jobs.runtimes.base import (
    DEFAULT_WORK_UNITS,
    JobArgumentError,
    Prepared,
    register,
    safe_join,
)
from haze.probe import encoders as encoder_probe

_SOFTWARE = {"libx264", "libx265", "libsvtav1", "libvpx-vp9"}
_CONTAINERS = {"mp4", "mkv", "webm", "mov"}

# Seconds of compute per second of video, on a node with speed_factor 1.0.
# Software encoding is roughly realtime and hardware encoding is several times
# faster than that, which is the whole reason `preferred_encoders` exists -- so
# the two must not be estimated identically, or the scheduler would see no
# compute advantage in the machine with the NVENC card.
SOFTWARE_REALTIME_FACTOR = 1.0
HARDWARE_REALTIME_FACTOR = 0.2


class FfmpegRuntime:
    name = "ffmpeg"
    description = "Transcode a video file"

    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def prepare(self, args: dict[str, Any], workdir: Path) -> Prepared:
        executable = shutil.which("ffmpeg")
        if executable is None:
            raise JobArgumentError("ffmpeg is not installed on this node")

        source = args.get("input")
        if not isinstance(source, str):
            raise JobArgumentError("`input` is required")
        input_path = safe_join(workdir, source)
        if not input_path.is_file():
            raise JobArgumentError(f"{source!r} was not found in the job's files")

        encoder = str(args.get("encoder", "libx264"))
        allowed = _SOFTWARE | set(encoder_probe.detect())
        if encoder not in allowed:
            raise JobArgumentError(
                f"encoder {encoder!r} is not available here. This node offers: "
                f"{', '.join(sorted(allowed))}"
            )

        container = str(args.get("container", "mp4")).lower()
        if container not in _CONTAINERS:
            raise JobArgumentError(f"`container` must be one of {', '.join(sorted(_CONTAINERS))}")

        crf = args.get("crf", 23)
        if not isinstance(crf, int) or not 0 <= crf <= 51:
            raise JobArgumentError("`crf` must be an integer between 0 and 51")

        outdir = workdir / "out"
        outdir.mkdir(exist_ok=True)
        output = outdir / f"{input_path.stem}.{container}"

        argv = [
            executable, "-hide_banner", "-nostdin", "-y",
            "-i", str(input_path),
            "-c:v", encoder,
            *(["-crf", str(crf)] if encoder in _SOFTWARE else ["-cq", str(crf)]),
            "-c:a", "copy",
            # Machine-readable progress on stdout. Without -nostats ffmpeg also
            # writes its carriage-return status line, which is designed for a
            # terminal and useless to parse.
            "-progress", "pipe:1", "-nostats",
            str(output),
        ]

        return Prepared(
            argv=argv,
            parser=FfmpegProgressParser(media.duration_seconds(input_path)),
            cwd=workdir,
            explicit_outputs=[output],
        )

    def estimate_work_units(self, args: dict[str, Any], inputs: list[Path]) -> float:
        """Video duration times a realtime factor for the chosen encoder.

        Duration rather than file size: bitrate varies by an order of magnitude
        between a phone clip and a ProRes master, so bytes are a poor proxy for
        how long a transcode takes -- and this is exactly the runtime where the
        transfer-versus-compute trade-off is decided.
        """
        seconds = media.duration_of_named(args.get("input"), inputs)
        if seconds is None:
            return DEFAULT_WORK_UNITS
        encoder = str(args.get("encoder", "libx264"))
        factor = (
            SOFTWARE_REALTIME_FACTOR if encoder in _SOFTWARE else HARDWARE_REALTIME_FACTOR
        )
        return max(seconds * factor, 0.1)


register(FfmpegRuntime())
