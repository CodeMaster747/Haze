"""Headless Blender renders.

The motivating example for the whole project: a laptop asks a desktop with a
real GPU to render, and watches the frames appear.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from haze.jobs.progress import BlenderProgressParser
from haze.jobs.runtimes.base import JobArgumentError, Prepared, register, safe_join

# Blender's own device names. An allowlist rather than a pass-through, because
# this value reaches a command line.
_DEVICES = {"CPU", "CUDA", "OPTIX", "HIP", "METAL", "ONEAPI"}


class BlenderRuntime:
    name = "blender"
    description = "Render frames from a .blend file"

    def available(self) -> bool:
        return shutil.which("blender") is not None

    def prepare(self, args: dict[str, Any], workdir: Path) -> Prepared:
        executable = shutil.which("blender")
        if executable is None:
            raise JobArgumentError("blender is not installed on this node")

        blend = args.get("blend_file")
        if not isinstance(blend, str):
            raise JobArgumentError("`blend_file` is required")
        # Resolved strictly inside the job directory: the submitter names a file
        # it uploaded, never an arbitrary path on this machine.
        blend_path = safe_join(workdir, blend)
        if not blend_path.is_file():
            raise JobArgumentError(f"{blend!r} was not found in the job's files")

        start = args.get("frame_start", 1)
        end = args.get("frame_end", start)
        if not isinstance(start, int) or not isinstance(end, int):
            raise JobArgumentError("`frame_start` and `frame_end` must be integers")
        if not 1 <= start <= end <= 100_000:
            raise JobArgumentError("frame range must satisfy 1 <= start <= end <= 100000")
        if end - start >= 10_000:
            raise JobArgumentError("refusing a range of 10000+ frames in one job")

        device = str(args.get("device", "CPU")).upper()
        if device not in _DEVICES:
            raise JobArgumentError(f"`device` must be one of {', '.join(sorted(_DEVICES))}")

        outdir = workdir / "out"
        outdir.mkdir(exist_ok=True)

        argv = [
            executable,
            "-b", str(blend_path),
            "-o", str(outdir / "####"),
            "-F", "PNG",
            # -s/-e must precede -a: Blender applies flags in order, so setting
            # the range after the render command silently renders frame 1 only.
            "-s", str(start),
            "-e", str(end),
            "-a",
        ]
        if device != "CPU":
            # Cycles-only flags; harmless on other engines.
            argv[3:3] = ["-E", "CYCLES"]
            argv += ["--", "--cycles-device", device]

        return Prepared(
            argv=argv,
            parser=BlenderProgressParser(start, end),
            cwd=workdir,
            outputs_from="parser",
        )


register(BlenderRuntime())
