"""Bounding what a job can consume.

This is the honest part of the project. The user sets a cap; how well it can be
enforced depends entirely on the operating system, and Haze says which it got
rather than implying uniform enforcement:

============  =============================================================
Linux         cgroups v2 via ``systemd-run --user --scope`` where available:
              real memory and CPU-quota enforcement, imposed by the kernel.
              Falls back to rlimits.
Windows       Job Objects: a job-wide commit limit and a hard CPU-rate cap,
              both imposed by the kernel on the whole process tree. Note the
              memory limit does not kill -- it makes the allocation *fail*
              (``MemoryError``, NULL from ``malloc``), so a job that handles
              that gracefully keeps running inside its cap. Real enforcement,
              different shape from Linux's OOM kill.
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
import functools
import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

import psutil

try:
    import resource
except ImportError:  # Windows has no rlimits at all; preexec_for returns None there.
    resource = None  # type: ignore[assignment]

from haze import log
from haze.jobs import winjob

_log = log.get("jobs.limits")


class Strength(enum.StrEnum):
    KERNEL = "kernel"
    """Enforced by the OS: the kernel prevents or punishes the breach, rather
    than the executor merely noticing it afterwards. What that looks like
    differs by platform -- Linux OOM-kills a cgroup that exceeds MemoryMax;
    Windows fails the allocation inside the process. Both are real. Only one
    of them is fatal."""
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


@functools.lru_cache(maxsize=1)
def _systemd_run_available() -> bool:
    """True when we can put a job in its own cgroup v2 scope, unprivileged.

    Cached: this spawns a subprocess with a 5-second timeout, and
    ``describe_platform`` is called from ``Caps.to_dict`` on *every* dashboard
    job update -- from the event loop. Uncached, a job that emits progress
    several times a second would spend the agent's whole event loop probing
    systemd. The answer cannot change while the process is running.
    """
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
        # A Job Object is a kernel object, not an argv prefix, so this seam can
        # only ever *report* on Windows -- the enforcement is attached to the
        # process after it exists, in attach_windows_job(). Stay ADVISORY here;
        # the strength is upgraded only once the assignment is confirmed.
        enforcement.notes.append("Windows Job Object pending: not yet attached")
        return argv, enforcement

    enforcement.notes.append(f"unknown platform {system!r}; caps are advisory")
    return argv, enforcement


def preexec_for(
    ram_bytes: int, wall_seconds: int, cpu_cores: int = 1, nice_by: int = 5
) -> Callable[[], None] | None:
    """A ``preexec_fn`` applying rlimits in the child before exec.

    Returns None on Windows, which has no fork and no rlimits.

    Note the deliberate niceness: a job arriving from another machine should
    lose to whatever its owner is doing locally. Somebody's laptop becoming
    unusable because they lent it out is how this feature stops being used.

    The new process group is *not* set here -- the executor passes
    ``start_new_session=True`` instead, which CPython performs in C between
    fork and exec rather than running interpreter code in a forked child that
    holds locks from the agent's other threads.
    """
    if platform.system() == "Windows" or resource is None:
        return None

    def apply() -> None:  # pragma: no cover -- runs in the forked child
        with_soft = min(ram_bytes, resource.RLIM_INFINITY)
        # Some platforms refuse; the executor's own monitor still applies.
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_AS, (with_soft, with_soft))

        # A second line of defence behind the executor's own timer: if the
        # agent dies, the kernel still stops the job.
        #
        # Scaled by cores, because RLIMIT_CPU counts CPU seconds summed across
        # threads while wall_seconds is wall clock. Unscaled, a 4-core job with
        # a 2-hour budget is killed after ~30 minutes and _describe_exit
        # truthfully reports "exceeded its CPU time limit" for a job that was
        # well inside the limit its submitter set.
        cpu_budget = wall_seconds * max(1, cpu_cores)
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_budget, cpu_budget + 5))

        with contextlib.suppress(OSError):
            os.nice(nice_by)

    return apply


@dataclass(frozen=True)
class SpawnPlan:
    """How to spawn a job's process on this platform.

    Both fields are always passed to ``create_subprocess_exec``: CPython
    rejects ``creationflags != 0`` on POSIX and ``preexec_fn is not None`` on
    Windows, and each is inert on the other platform.
    """

    preexec: Callable[[], None] | None = None
    creationflags: int = 0
    resume_needed: bool = False
    """Windows only. The child was created suspended so the Job Object can be
    attached before it runs; the executor must resume it."""


def spawn_plan(ram_bytes: int, wall_seconds: int, cpu_cores: int) -> SpawnPlan:
    if platform.system() != "Windows":
        return SpawnPlan(preexec=preexec_for(ram_bytes, wall_seconds, cpu_cores))

    # CREATE_SUSPENDED closes the one gap that matters: without it, a job that
    # spawns a helper in its first microseconds produces a grandchild that is
    # in no job object at all, which TerminateJobObject will never kill -- the
    # exact escape the cap exists to prevent.
    #
    # CREATE_NEW_PROCESS_GROUP makes the child its own group, so a Ctrl+Break
    # aimed at it does not travel back to the agent.
    flags = winjob.CREATE_SUSPENDED | winjob.CREATE_NEW_PROCESS_GROUP
    if not winjob.has_console():
        # A console application launched from a console-less parent gets a
        # console allocated for it -- ffmpeg windows popping up on the desktop
        # of someone who is quietly lending out their machine.
        flags |= winjob.CREATE_NO_WINDOW
    return SpawnPlan(creationflags=flags, resume_needed=True)


def attach_windows_job(
    pid: int, ram_bytes: int, cpu_cores: int, enforcement: Enforcement
) -> winjob.WindowsJobObject | None:
    """Put a freshly spawned process into a Job Object, and record the truth.

    Mutates ``enforcement`` in place. Only reports KERNEL for what the kernel
    was actually told to enforce: memory and CPU are tracked separately because
    CPU rate control can fail on its own, and claiming a cap we did not set is
    the one outcome this module exists to prevent.

    Never raises. If the whole thing fails the job still runs -- a node that
    refuses work because Job Objects were unavailable is worse than one that
    runs it and says the caps are advisory.
    """
    logical = psutil.cpu_count(logical=True) or 1
    job = winjob.WindowsJobObject.create(ram_bytes, cpu_cores, logical)
    if job is None:
        enforcement.notes[:] = [
            "could not create a Windows Job Object; caps are monitored and the "
            "job is killed on breach, but nothing prevents the breach"
        ]
        return None

    failure = job.assign(pid)
    if failure is not None:
        job.close()
        enforcement.notes[:] = [
            f"could not apply a Windows Job Object ({failure}); caps are "
            "monitored and the job is killed on breach, but nothing prevents "
            "the breach"
        ]
        return None

    rate = winjob.cpu_rate(cpu_cores, logical)
    enforcement.ram = Strength.KERNEL
    notes = [
        f"Windows Job Object: {ram_bytes // 2**20} MiB job-wide commit limit. "
        "Allocations past it fail inside the job rather than the job being "
        "killed -- real enforcement, but not Linux's OOM kill"
    ]
    if job.cpu_capped:
        enforcement.cpu = Strength.KERNEL
        notes.append(
            f"hard CPU cap of {rate / 100:.1f}% of this machine "
            f"({cpu_cores} of {logical} logical processors)"
        )
    else:
        notes.append(
            "CPU rate control was refused by this Windows build, so the CPU "
            "share is advisory"
        )
    if not job.priority_lowered:
        notes.append("below-normal priority was not applied")
    notes.append("the whole process tree dies with the job object")
    enforcement.notes[:] = notes
    return job


def platform_enforces() -> bool:
    """Whether this OS can hold the memory and CPU caps at all.

    The structural form of :func:`describe_platform`, for a UI that would
    otherwise have to search English prose for a phrase to decide whether to
    warn -- which is exactly how a Windows node ended up showing no warning at
    all while enforcing nothing.
    """
    system = platform.system()
    if system == "Linux":
        return _systemd_run_available()
    return system == "Windows"


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
        return (
            "Windows Job Objects enforce memory and CPU caps (a memory cap "
            "makes allocations fail rather than killing the job)"
        )
    return f"{system}: caps are advisory"
