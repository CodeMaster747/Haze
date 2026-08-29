"""Which hardware video encoders this machine can actually use.

Detected by asking ffmpeg, not by inferring from the GPU vendor: a machine can
have an NVIDIA card and an ffmpeg built without NVENC, and the scheduler needs
to know what will really run rather than what ought to.

This is a genuine scheduler input, and the most convincing one available --
"send the HEVC encode to the node with NVENC" is a placement decision a user
can immediately see the sense of, and it costs almost nothing to support.
"""

from __future__ import annotations

import functools
import shutil
import subprocess

from haze import log

_log = log.get("probe.encoders")

_TIMEOUT_S = 5.0

# Hardware-accelerated encoders worth advertising, in rough order of how much
# a job would prefer them. Software encoders (libx264 and friends) are omitted:
# every node has those, so they carry no scheduling signal.
_INTERESTING = (
    "av1_nvenc", "hevc_nvenc", "h264_nvenc",           # NVIDIA
    "av1_qsv", "hevc_qsv", "h264_qsv",                 # Intel Quick Sync
    "av1_vaapi", "hevc_vaapi", "h264_vaapi",           # Linux VA-API
    "hevc_videotoolbox", "h264_videotoolbox",          # Apple
    "hevc_amf", "h264_amf",                            # AMD
)


@functools.cache
def detect() -> list[str]:
    """Hardware encoders available here. Cached: this cannot change at runtime.

    Returns an empty list when ffmpeg is absent, which is a legitimate state --
    such a node simply never wins placement for an encode job.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        _log.info("ffmpeg not found: this node advertises no hardware encoders")
        return []

    try:
        result = subprocess.run(  # noqa: S603 -- resolved path, fixed argv
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-encoders"],
            capture_output=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log.warning("could not enumerate ffmpeg encoders: %s", exc)
        return []

    listing = result.stdout.decode("utf-8", errors="replace")
    # ffmpeg's rows look like " V....D h264_nvenc  NVIDIA NVENC H.264 encoder".
    # Matching on a whitespace-delimited token avoids "h264_nvenc" matching
    # inside some other encoder's description text.
    tokens = set(listing.split())
    found = [name for name in _INTERESTING if name in tokens]

    if found:
        _log.info("hardware encoders: %s", ", ".join(found))
    else:
        _log.info("ffmpeg present but no hardware encoders detected")
    return found
