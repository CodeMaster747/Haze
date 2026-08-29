"""Bounding what a job can consume.

This is the honest part of the project. The user sets a cap; how well it can be
enforced depends entirely on the operating system, and Haze says which it got
rather than implying uniform enforcement:

============  =============================================================
Linux         cgroups v2 via ``systemd-run --user --scope`` where available:
              real memory and CPU-quota enforcement, imposed by the kernel.
              Falls back to rlimits.
Windows       Job Objects would give real memory and CPU-rate control.
              Not implemented yet -- reported as ADVISORY, not claimed.
macOS         **No equivalent exists.** No cgroups, no Job Objects.
              ``setrlimit(RLIMIT_AS)`` and ``nice`` are what there is, and
              RLIMIT_AS bounds address space rather than resident memory, so
              a process that maps far more than it touches trips it while one
              that touches everything it maps may not. Treat as advisory.
============  =============================================================

:class:`Enforcement` records what was actually applied, and it travels to the
dashboard. A cap that silently is not enforced is worse than no cap: it makes
someone comfortable running a job they should have thought harder about.
"""

from __future__ import annotations

import contextlib
import enum
import os
import platform
import resource
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from haze import log

_log = log.get("jobs.limits")


class Strength(enum.StrEnum):
    KERNEL = "kernel"
    """Enforced by the OS. Exceeding it kills the process."""
    RLIMIT = "rlimit"
    """setrlimit. Real, but bounds address space rather than resident set."""
    ADVISORY = "advisory"
    """Recorded and monitored, not enforced. The executor still kills a job
    that exceeds it, but only after noticing -- which is not the same thing."""


@dataclass
class Enforcement:
    """What was actually applied to a job, and how strongly."""

    ram: Strength = Strength.ADVISORY
    cpu: Strength = Strength.ADVISORY
    wall: Strength = Strength.KERNEL
    """Wall-clock is always genuinely enforced: the executor holds the handle
    and kills the process group. No OS support needed."""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ram": self.ram.value,
            "cpu": self.cpu.value,
            "wall": self.wall.value,
            "notes": self.notes,
        }

    @property
    def fully_enforced(self) -> bool:
        return self.ram is Strength.KERNEL and self.cpu is Strength.KERNEL


def _systemd_run_available() -> bool:
    """True when we can put a job in its own cgroup v2 scope, unprivileged."""
    if platform.system() != "Linux":
        return False
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv
            [systemd_run, "--user", "--scope", "--quiet", "true"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def wrap_command(argv: list[str], ram_bytes: int, cpu_cores: int) -> tuple[list[str], Enforcement]:
    """Wrap ``argv`` so the OS enforces the caps, where it can.

    Returns the (possibly unchanged) argv and a record of what was achieved.
    """
    system = platform.system()
    enforcement = Enforcement()

    if system == "Linux" and _systemd_run_available():
        # MemoryMax is a hard kernel limit: the cgroup's processes are OOM-killed
        # on breach. CPUQuota is a genuine share of CPU time, not a priority hint.
        systemd_run = shutil.which("systemd-run") or "systemd-run"
        wrapped = [
            systemd_run, "--user", "--scope", "--quiet",
            f"--property=MemoryMax={ram_bytes}",
            f"--property=CPUQuota={cpu_cores * 100}%",
            *argv,
        ]
        enforcement.ram = Strength.KERNEL
        enforcement.cpu = Strength.KERNEL
        enforcement.notes.append("cgroups v2 scope via systemd-run")
        return wrapped, enforcement

    if system == "Linux":
        enforcement.ram = Strength.RLIMIT
        enforcement.notes.append(
            "systemd-run unavailable; using rlimits, which bound address space "
            "rather than resident memory"
        )
        return argv, enforcement

    if system == "Darwin":
        enforcement.ram = Strength.RLIMIT
        enforcement.cpu = Strength.ADVISORY
        enforcement.notes.append(
            "macOS has no cgroups or Job Objects. Memory is bounded with "
            "RLIMIT_AS (address space, not resident set) and CPU share is not "
            "enforceable -- only niced. Treat these caps as advisory."
        )
        return argv, enforcement

    if system == "Windows":
        enforcement.notes.append(
            "Windows Job Objects are not implemented yet; caps are monitored "
            "and the job is killed on breach, but nothing prevents the breach."
        )
        return argv, enforcement

    enforcement.notes.append(f"unknown platform {system!r}; caps are advisory")
    return argv, enforcement


def preexec_for(ram_bytes: int, wall_seconds: int, nice_by: int = 5) -> Callable[[], None] | None:
    """A ``preexec_fn`` applying rlimits in the child before exec.

    Returns None on Windows, which has no fork and no rlimits.

    Note the deliberate niceness: a job arriving from another machine should
    lose to whatever its owner is doing locally. Somebody's laptop becoming
    unusable because they lent it out is how this feature stops being used.
    """
    if platform.system() == "Windows":
        return None

    def apply() -> None:  # pragma: no cover -- runs in the forked child
        # New process group, so the executor can signal the whole tree. ffmpeg
        # and Blender both spawn helpers that would otherwise survive a kill.
        os.setpgrp()

        with_soft = min(ram_bytes, resource.RLIM_INFINITY)
        # Some platforms refuse; the executor's own monitor still applies.
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_AS, (with_soft, with_soft))

        # A second line of defence behind the executor's own timer: if the
        # agent dies, the kernel still stops the job.
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_CPU, (wall_seconds, wall_seconds + 5))

        with contextlib.suppress(OSError):
            os.nice(nice_by)

    return apply


def describe_platform() -> str:
    """One line for the dashboard, so the limitation is visible where the caps
    are set rather than buried in documentation."""
    system = platform.system()
    if system == "Linux":
        return (
            "cgroups v2 enforce memory and CPU caps"
            if _systemd_run_available()
            else "rlimits only (systemd-run unavailable); caps bound address space"
        )
    if system == "Darwin":
        return "macOS cannot enforce CPU or memory caps; they are advisory and monitored"
    if system == "Windows":
        return "Windows Job Objects not implemented; caps are monitored, not enforced"
    return f"{system}: caps are advisory"
