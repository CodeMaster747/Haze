"""Video transcoding.

The encoder is chosen from an allowlist and matched against what this node's
ffmpeg actually reports, so a job asking for NVENC on a machine without it
fails immediately with a clear message rather than after ffmpeg has spent a
minute discovering the same thing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from haze.jobs.progress import FfmpegProgressParser
from haze.jobs.runtimes.base import JobArgumentError, Prepared, register, safe_join
from haze.probe import encoders as encoder_probe

_SOFTWARE = {"libx264", "libx265", "libsvtav1", "libvpx-vp9"}
_CONTAINERS = {"mp4", "mkv", "webm", "mov"}


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
            parser=FfmpegProgressParser(_duration_of(input_path)),
            cwd=workdir,
            explicit_outputs=[output],
        )


def _duration_of(path: Path) -> float | None:
    """Media duration via ffprobe, so progress can be a real fraction.

    Returns None when ffprobe is absent or the file has no duration -- the
    parser then reports frames and rate but no percentage, which is honest.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 -- resolved path, fixed argv
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=15, check=False,
        )
        return float(result.stdout.decode().strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


register(FfmpegRuntime())
