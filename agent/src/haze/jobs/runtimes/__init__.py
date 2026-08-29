"""Runtime allowlist.

Importing this package registers every runtime. Adding one means adding it
here deliberately -- there is no plugin discovery, because a plugin mechanism
is a way for something unexpected to become executable.
"""

from haze.jobs.runtimes import blender, ffmpeg, hashbench  # noqa: F401
from haze.jobs.runtimes.base import (
    REGISTRY,
    JobArgumentError,
    Prepared,
    Runtime,
    available_names,
    get,
    register,
    safe_join,
)

__all__ = [
    "REGISTRY",
    "JobArgumentError",
    "Prepared",
    "Runtime",
    "available_names",
    "get",
    "register",
    "safe_join",
]
