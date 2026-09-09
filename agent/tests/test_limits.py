"""What Haze claims to enforce, and whether it actually does.

The module under test is the project's honesty artifact: it reports the
*strength* of each cap rather than implying uniform enforcement. So these tests
are mostly about the failure paths -- a cap that silently is not enforced is
worse than no cap, and the way that happens is a Job Object call failing while
we go on reporting KERNEL.

None of this needs Windows. The arithmetic and the structure layouts are pure,
and the kernel32 calls sit behind a single injectable name.
"""

from __future__ import annotations

import ctypes
import signal

import pytest

from haze.jobs import executor, limits, winjob
from haze.jobs.limits import Strength

pytestmark = pytest.mark.skipif(
    ctypes.sizeof(ctypes.c_void_p) != 8,
    reason="the structure layouts asserted here are the 64-bit ones",
)


# --- structures ------------------------------------------------------------


def test_the_structures_match_the_win32_headers():
    """The highest-value test here.

    A field in the wrong order does not fail loudly: it writes the memory limit
    into PeakProcessMemoryUsed, the cap does nothing at all, and Haze reports
    KERNEL for it. c_size_t is 8 bytes on 64-bit Linux and macOS too, so this
    checks the real layout on any runner we have.
    """
    basic = winjob.JOBOBJECT_BASIC_LIMIT_INFORMATION
    extended = winjob.JOBOBJECT_EXTENDED_LIMIT_INFORMATION

    assert ctypes.sizeof(basic) == 64
    assert ctypes.sizeof(winjob.IO_COUNTERS) == 48
    assert ctypes.sizeof(extended) == 144
    assert ctypes.sizeof(winjob.JOBOBJECT_CPU_RATE_CONTROL_INFORMATION) == 8

    assert basic.LimitFlags.offset == 16
    assert basic.MinimumWorkingSetSize.offset == 24
    assert basic.Affinity.offset == 48
    assert extended.IoInfo.offset == 64
    assert extended.JobMemoryLimit.offset == 120


def test_a_cpu_cap_is_a_share_of_the_whole_machine_not_of_one_core():
    """CpuRate is out of 10000 for every logical processor, where the Linux
    equivalent (CPUQuota=200%) counts cores. Porting the Linux formula over is
    the obvious mistake and would hand a job eight times what it asked for."""
    assert winjob.cpu_rate(2, 16) == 1250
    assert winjob.cpu_rate(2, 8) == 2500
    assert winjob.cpu_rate(1, 24) == 417
    assert winjob.cpu_rate(16, 8) == 10000, "never more than the whole machine"
    assert winjob.cpu_rate(1, 100000) == 1, "never zero, which would mean no CPU at all"


def test_the_memory_limit_is_a_job_wide_commit_limit():
    info = winjob.extended_limit_info(2 << 30)
    assert info.JobMemoryLimit == 2 << 30
    assert info.ProcessMemoryLimit == 0, "the cap is on the tree, not each process"

    flags = info.BasicLimitInformation.LimitFlags
    assert flags & winjob.JOB_OBJECT_LIMIT_JOB_MEMORY
    assert flags & winjob.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert flags & winjob.JOB_OBJECT_LIMIT_PRIORITY_CLASS
    assert info.BasicLimitInformation.PriorityClass == winjob.BELOW_NORMAL_PRIORITY_CLASS

    plain = winjob.extended_limit_info(1 << 30, below_normal=False)
    assert not plain.BasicLimitInformation.LimitFlags & winjob.JOB_OBJECT_LIMIT_PRIORITY_CLASS


def test_a_cpu_rate_without_a_hard_cap_would_only_be_a_hint():
    info = winjob.cpu_rate_info(1250)
    assert info.Value.CpuRate == 1250
    assert info.ControlFlags & winjob.JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
    assert info.ControlFlags & winjob.JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP


# --- a fake kernel32 -------------------------------------------------------


class FakeKernel32:
    """Records what was asked of Windows, and can refuse any of it."""

    def __init__(self, *, create=True, open_process=True, assign=True,
                 set_info=(True, True), console=False):
        self._create = create
        self._open = open_process
        self._assign = assign
        self._set_info = list(set_info)
        self._console = console
        self.last_error = 0
        self.info_calls: list[tuple[int, object]] = []
        self.terminated = False
        self.closed: list[int] = []

    def CreateJobObjectW(self, attributes, name):
        assert name is None, "a named job is global; two agents would collide"
        return 0x1234 if self._create else None

    def SetInformationJobObject(self, handle, info_class, info, size):
        # byref() keeps the original alive on ._obj, so the test can see the
        # values that would have reached the kernel.
        self.info_calls.append((info_class, getattr(info, "_obj", None)))
        return 1 if self._set_info.pop(0) else 0

    def OpenProcess(self, access, inherit, pid):
        return 0x5678 if self._open else None

    def AssignProcessToJobObject(self, job, process):
        return 1 if self._assign else 0

    def TerminateJobObject(self, job, code):
        self.terminated = True
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1

    def GetConsoleWindow(self):
        return 0x9999 if self._console else None


@pytest.fixture
def fake(monkeypatch):
    """Install a fake kernel32 and a deterministic core count."""
    def install(**kwargs):
        lib = FakeKernel32(**kwargs)
        monkeypatch.setattr(winjob, "_kernel32", lambda: lib)
        monkeypatch.setattr(winjob, "_last_error", lambda: lib.last_error)
        monkeypatch.setattr(limits.psutil, "cpu_count", lambda logical=True: 16)
        return lib
    return install


# --- what we claim, versus what we did ------------------------------------


def test_a_job_object_that_was_actually_applied_is_reported_as_kernel(fake):
    lib = fake()
    enforcement = limits.Enforcement()

    guard = limits.attach_windows_job(4321, 4 << 30, 2, enforcement)

    assert guard is not None
    assert enforcement.ram is Strength.KERNEL
    assert enforcement.cpu is Strength.KERNEL
    assert enforcement.fully_enforced

    classes = [c for c, _ in lib.info_calls]
    assert classes == [winjob.JOB_INFO_EXTENDED_LIMIT, winjob.JOB_INFO_CPU_RATE_CONTROL]
    limit_info = lib.info_calls[0][1]
    assert limit_info.JobMemoryLimit == 4 << 30, "the cap the caller asked for"
    assert lib.info_calls[1][1].Value.CpuRate == 1250, "2 of 16 logical processors"

    notes = " ".join(enforcement.notes)
    assert "4096 MiB" in notes
    assert "not Linux's OOM kill" in notes, "the difference must not be papered over"
    assert 0x5678 in lib.closed, "the OpenProcess handle is not the job handle"


def test_a_job_object_that_could_not_be_created_stays_advisory(fake):
    """The regression test for the property this module exists to protect."""
    fake(create=False)
    enforcement = limits.Enforcement()

    guard = limits.attach_windows_job(4321, 1 << 30, 2, enforcement)

    assert guard is None
    assert enforcement.ram is Strength.ADVISORY
    assert enforcement.cpu is Strength.ADVISORY
    assert not enforcement.fully_enforced
    assert "nothing prevents the breach" in " ".join(enforcement.notes)


def test_an_agent_already_inside_a_job_object_says_so(fake):
    lib = fake(assign=False)
    lib.last_error = winjob.ERROR_ACCESS_DENIED
    enforcement = limits.Enforcement()

    assert limits.attach_windows_job(4321, 1 << 30, 2, enforcement) is None
    assert enforcement.ram is Strength.ADVISORY
    assert "already inside a job object" in " ".join(enforcement.notes)


def test_a_process_that_was_never_assigned_is_never_reported_as_enforced(fake):
    """Setting limits on a job enforces nothing until something is in it."""
    fake(open_process=False)
    enforcement = limits.Enforcement()

    assert limits.attach_windows_job(4321, 1 << 30, 2, enforcement) is None
    assert enforcement.ram is Strength.ADVISORY
    assert "OpenProcess failed" in " ".join(enforcement.notes)


def test_memory_can_be_enforced_while_cpu_is_not(fake):
    """CPU rate control needs Windows 8+ and can fail on its own. Reporting the
    memory cap it did get is right; reporting a CPU cap it did not is not."""
    fake(set_info=(True, False))
    enforcement = limits.Enforcement()

    guard = limits.attach_windows_job(4321, 1 << 30, 2, enforcement)

    assert guard is not None
    assert enforcement.ram is Strength.KERNEL
    assert enforcement.cpu is Strength.ADVISORY
    assert not enforcement.fully_enforced
    assert "CPU share is advisory" in " ".join(enforcement.notes)


def test_the_nice_level_is_dropped_rather_than_the_cpu_cap(fake):
    """Some builds refuse CPU rate control alongside a priority-class limit.
    A real CPU cap is worth more than a politeness setting."""
    lib = fake(set_info=(True, False, True, True))
    lib.last_error = winjob.ERROR_INVALID_PARAMETER
    enforcement = limits.Enforcement()

    guard = limits.attach_windows_job(4321, 1 << 30, 2, enforcement)

    assert guard is not None and guard.cpu_capped and not guard.priority_lowered
    assert enforcement.cpu is Strength.KERNEL
    assert "below-normal priority was not applied" in " ".join(enforcement.notes)
    retried = lib.info_calls[2][1]
    assert not retried.BasicLimitInformation.LimitFlags & winjob.JOB_OBJECT_LIMIT_PRIORITY_CLASS


def test_closing_the_guard_is_idempotent(fake):
    lib = fake()
    guard = winjob.WindowsJobObject.create(1 << 30, 2, 16)
    assert guard is not None

    guard.close()
    guard.close()
    assert lib.closed.count(0x1234) == 1
    assert guard.terminate() is False, "a closed job has nothing left to kill"


# --- the spawn plan --------------------------------------------------------


# The two halves are separate tests, and only one of them is portable.
# `spawn_plan`'s Windows branch is pure arithmetic over constants, so it can be
# asserted anywhere; its POSIX branch cannot, because `preexec_for` returns None
# when the `resource` module is missing -- which on Windows is not a mock but the
# truth. Asserting both in one function meant the POSIX half silently depended on
# the host being POSIX, and it failed the first time this suite ran on Windows.
def test_the_windows_spawn_plan_passes_no_preexec_fn(monkeypatch):
    """CPython rejects creationflags on POSIX and preexec_fn on Windows, and
    the executor's spawn catches ValueError -- so getting this wrong would
    surface as a confusing 'could not start' rather than a crash."""
    monkeypatch.setattr(limits.platform, "system", lambda: "Windows")
    win = limits.spawn_plan(1 << 30, 60, 2)
    assert win.preexec is None
    assert win.resume_needed, "a suspended child that is never resumed hangs forever"
    assert win.creationflags & winjob.CREATE_SUSPENDED
    assert win.creationflags & winjob.CREATE_NEW_PROCESS_GROUP


@pytest.mark.skipif(
    limits.resource is None, reason="the POSIX plan needs the resource module"
)
def test_the_posix_spawn_plan_sets_no_creationflags(monkeypatch):
    """The mirror of the above: creationflags must stay 0 where CPython would
    reject a non-zero one."""
    monkeypatch.setattr(limits.platform, "system", lambda: "Linux")
    posix = limits.spawn_plan(1 << 30, 60, 2)
    assert posix.creationflags == 0
    assert posix.preexec is not None
    assert not posix.resume_needed


def test_wrap_command_never_claims_windows_enforcement_up_front(monkeypatch):
    """A Job Object cannot be an argv prefix, so this seam can only report --
    and until the process exists there is nothing to report."""
    monkeypatch.setattr(limits.platform, "system", lambda: "Windows")
    argv, enforcement = limits.wrap_command(["blender", "-b"], 1 << 30, 2)

    assert argv == ["blender", "-b"], "nothing to wrap"
    assert enforcement.ram is Strength.ADVISORY
    assert enforcement.cpu is Strength.ADVISORY


# --- exit codes ------------------------------------------------------------


def test_windows_exit_codes_are_read_as_unsigned():
    """An access violation arrives as 3221225477, not as a negative number, so
    the POSIX `exit_code < 0` branch never fires on Windows."""
    assert "access violation" in str(executor._describe_windows_exit(3221225477))
    assert executor._describe_windows_exit(-1073741819) == (
        executor._describe_windows_exit(0xC0000005)
    ), "the same status, whichever sign convention produced it"

    assert "memory" in str(executor._describe_windows_exit(0xC0000017))
    assert executor._describe_windows_exit(1) is None, (
        "1 is an ordinary failure; mapping it would mislabel every exit(1)"
    )
    assert executor._describe_windows_exit(0) is None


@pytest.mark.skipif(not hasattr(signal, "SIGXCPU"), reason="POSIX signals only")
def test_a_posix_signal_is_still_named():
    """The existing behaviour, unchanged by the Windows work."""
    described = executor._describe_exit(-int(signal.SIGXCPU), [])
    assert "CPU time limit" in described
    assert "code" not in described, "the raw number is meaningless to a human"
