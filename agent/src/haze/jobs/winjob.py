"""Windows Job Objects -- the one facility Windows has for bounding a process tree.

A Job Object is a kernel object you put processes into. Limits set on it apply
to every process in it, including ones spawned later, which is exactly the
property ``_tree_rss`` in the executor exists to approximate by hand.

Two things about it are worth knowing before reading the rest, because they are
what the honesty in :mod:`haze.jobs.limits` turns on:

**A memory limit here is a commit limit, and it is not fatal.** Exceeding
``JobMemoryLimit`` does not kill anything. The allocation simply fails --
``VirtualAlloc`` returns NULL, ``malloc`` returns NULL, ``new`` throws
``std::bad_alloc``, Python raises ``MemoryError``. This is genuinely enforced by
the kernel (the cap cannot be exceeded, ever) but it is *not* the cgroups v2
story of an OOM kill, and a well-written job may notice, back off, and carry on
inside its cap. That is a success, not a failure.

**A CPU rate is a share of the whole machine.** ``CpuRate`` is in hundredths of
a percent where 10000 means every logical processor -- unlike systemd's
``CPUQuota=200%``, which means two cores. See :func:`cpu_rate`.

Everything here is ``ctypes``. Adding a dependency for six kernel32 calls would
be a poor trade in a project that justifies each one it has.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys

from haze import log

_log = log.get("jobs.winjob")

# --- constants -------------------------------------------------------------
# JOBOBJECTINFOCLASS. Named in UPPER_SNAKE rather than the header's PascalCase
# so they read as the constants they are (and so ruff's N816 stays quiet).
JOB_INFO_EXTENDED_LIMIT = 9
JOB_INFO_CPU_RATE_CONTROL = 15

# JOBOBJECT_BASIC_LIMIT_INFORMATION.LimitFlags
JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

# JOBOBJECT_CPU_RATE_CONTROL_INFORMATION.ControlFlags
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004

CPU_RATE_SCALE = 10000
"""``CpuRate`` units: 10000 == 100% of every logical processor on the machine."""

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100

# CreateProcess flags. Mirrored from subprocess rather than imported, because
# subprocess only defines them on Windows and this module must import anywhere.
CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

CTRL_BREAK_EVENT = 1
"""``signal.CTRL_BREAK_EVENT``, spelled out because the ``signal`` module only
defines it on Windows -- and every Windows-only symbol lives in this module, so
that everything else typechecks natively on both branches."""

ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87


# --- structures ------------------------------------------------------------
# Field names are the Win32 header's, verbatim: the only thing that makes a
# ctypes translation auditable is being able to paste a name into the SDK docs
# and compare field for field. No _pack_ -- Windows headers use default packing,
# which is exactly ctypes' natural alignment for these types, and _pack_ = 1
# would shift every field after LimitFlags and silently corrupt the limits.
#
# The bare annotations are not decoration. ctypes builds the field descriptors
# dynamically, so without them mypy strict rejects every attribute access. PEP
# 526 bare annotations create no class attribute, so ctypes is unaffected.


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    PerProcessUserTimeLimit: int
    PerJobUserTimeLimit: int
    LimitFlags: int
    MinimumWorkingSetSize: int
    MaximumWorkingSetSize: int
    ActiveProcessLimit: int
    Affinity: int
    PriorityClass: int
    SchedulingClass: int

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),   # LARGE_INTEGER  off 0
        ("PerJobUserTimeLimit", ctypes.c_int64),       # LARGE_INTEGER  off 8
        ("LimitFlags", ctypes.c_uint32),               # DWORD          off 16
        ("MinimumWorkingSetSize", ctypes.c_size_t),    # SIZE_T         off 24
        ("MaximumWorkingSetSize", ctypes.c_size_t),    # SIZE_T         off 32
        ("ActiveProcessLimit", ctypes.c_uint32),       # DWORD          off 40
        ("Affinity", ctypes.c_size_t),                 # ULONG_PTR      off 48
        ("PriorityClass", ctypes.c_uint32),            # DWORD          off 56
        ("SchedulingClass", ctypes.c_uint32),          # DWORD          off 60
    ]                                                  # sizeof == 64


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]                                                  # sizeof == 48


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    BasicLimitInformation: JOBOBJECT_BASIC_LIMIT_INFORMATION
    IoInfo: IO_COUNTERS
    ProcessMemoryLimit: int
    JobMemoryLimit: int
    PeakProcessMemoryUsed: int
    PeakJobMemoryUsed: int

    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),  # off 0
        ("IoInfo", IO_COUNTERS),                                       # off 64
        ("ProcessMemoryLimit", ctypes.c_size_t),                       # off 112
        ("JobMemoryLimit", ctypes.c_size_t),                           # off 120
        ("PeakProcessMemoryUsed", ctypes.c_size_t),                    # off 128
        ("PeakJobMemoryUsed", ctypes.c_size_t),                        # off 136
    ]                                                                  # sizeof == 144


class _CPU_RATE_MIN_MAX(ctypes.Structure):
    _fields_ = [("MinRate", ctypes.c_uint16), ("MaxRate", ctypes.c_uint16)]


class _CPU_RATE_VALUE(ctypes.Union):
    CpuRate: int
    Weight: int

    _fields_ = [
        ("CpuRate", ctypes.c_uint32),
        ("Weight", ctypes.c_uint32),
        ("MinMax", _CPU_RATE_MIN_MAX),
    ]


class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    ControlFlags: int
    Value: _CPU_RATE_VALUE

    # The header makes the union anonymous. Naming it keeps the mypy annotation
    # unambiguous at the cost of one extra `.Value` at each use.
    _fields_ = [("ControlFlags", ctypes.c_uint32), ("Value", _CPU_RATE_VALUE)]
    # sizeof == 8


# --- pure builders ---------------------------------------------------------
# Everything below this line up to _load_kernel32 runs, and is tested, on any
# platform. That is deliberate: the arithmetic and the flag composition are
# where a silent mistake would report KERNEL while enforcing nothing.


def cpu_rate(cpu_cores: int, logical_cpus: int) -> int:
    """``CpuRate`` for a cap of ``cpu_cores``, in hundredths of a percent.

    The scale is the *whole machine*, not one core: 2 cores of a 16-thread box
    is 1250 (12.5%), where the Linux equivalent is ``CPUQuota=200%``. Porting
    the Linux formula across is the obvious mistake and it would hand a job
    eight times what it asked for.
    """
    rate = round(CPU_RATE_SCALE * cpu_cores / max(1, logical_cpus))
    return max(1, min(CPU_RATE_SCALE, rate))


def extended_limit_info(
    ram_bytes: int, *, below_normal: bool = True
) -> JOBOBJECT_EXTENDED_LIMIT_INFORMATION:
    """The job-wide commit limit, plus kill-on-close, plus (usually) low priority.

    ``JobMemoryLimit`` rather than ``ProcessMemoryLimit``: the cap is on the
    tree, matching what ``_tree_rss`` measures. A job that forks four helpers
    does not get four times its cap.

    ``below_normal`` is the direct analogue of the deliberate ``os.nice(5)`` in
    ``limits.preexec_for``, and for the same reason -- somebody's laptop
    becoming unusable because they lent it out is how this feature stops being
    used.
    """
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    flags = JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if below_normal:
        flags |= JOB_OBJECT_LIMIT_PRIORITY_CLASS
        info.BasicLimitInformation.PriorityClass = BELOW_NORMAL_PRIORITY_CLASS
    info.BasicLimitInformation.LimitFlags = flags
    info.JobMemoryLimit = ram_bytes
    return info


def cpu_rate_info(rate: int) -> JOBOBJECT_CPU_RATE_CONTROL_INFORMATION:
    """A hard CPU cap. Without HARD_CAP the rate is only a scheduling weight."""
    info = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    info.ControlFlags = (
        JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
    )
    info.Value.CpuRate = rate
    return info


# --- the kernel32 seam -----------------------------------------------------

_KERNEL32: ctypes.CDLL | None = None


def _load_kernel32() -> ctypes.CDLL:
    """Bind kernel32 with explicit signatures.

    The ``restype`` lines are the ones that matter. ctypes defaults a return
    type to ``c_int``, which truncates a 64-bit HANDLE to 32 bits -- the job
    handle then looks plausible and every subsequent call fails with
    ERROR_INVALID_HANDLE. That failure is silent and would leave us reporting
    KERNEL while enforcing nothing, which is the exact outcome this module is
    written to prevent.
    """
    if sys.platform != "win32":
        raise OSError("Job Objects exist only on Windows")

    dll = ctypes.WinDLL("kernel32", use_last_error=True)

    dll.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    dll.CreateJobObjectW.restype = ctypes.c_void_p
    dll.SetInformationJobObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
    ]
    dll.SetInformationJobObject.restype = ctypes.c_int
    dll.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.AssignProcessToJobObject.restype = ctypes.c_int
    dll.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    dll.OpenProcess.restype = ctypes.c_void_p
    dll.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    dll.TerminateJobObject.restype = ctypes.c_int
    dll.CloseHandle.argtypes = [ctypes.c_void_p]
    dll.CloseHandle.restype = ctypes.c_int
    dll.GetConsoleWindow.argtypes = []
    dll.GetConsoleWindow.restype = ctypes.c_void_p
    return dll


def _kernel32() -> ctypes.CDLL:
    """The kernel32 binding, loaded once.

    A function rather than a module constant so that nothing is loaded on
    import, and so that this one name is the whole test seam: the suite
    monkeypatches ``winjob._kernel32`` with a duck-typed fake and exercises
    every branch below on Linux. All the ``argtypes`` plumbing lives in
    :func:`_load_kernel32`, so the fake only has to be callable.
    """
    global _KERNEL32
    if _KERNEL32 is None:
        _KERNEL32 = _load_kernel32()
    return _KERNEL32


def _last_error() -> int:
    """``GetLastError``, or 0 off-Windows. ``ctypes.get_last_error`` is itself
    Windows-only, so it cannot be called unguarded."""
    if sys.platform != "win32":
        return 0
    return ctypes.get_last_error()


def has_console() -> bool:
    """Whether this agent owns a console.

    Decides two things: whether a console-application child would get a window
    of its own popped up on the owner's desktop (see CREATE_NO_WINDOW), and
    whether a Ctrl+Break can be delivered to it at all.
    """
    try:
        return bool(_kernel32().GetConsoleWindow())
    except OSError:
        return False


# --- the job object --------------------------------------------------------


class WindowsJobObject:
    """A job object holding one job's process tree.

    Close it to kill the tree: KILL_ON_JOB_CLOSE means the handle *is* the kill
    switch. That also makes the agent's own death a clean sweep -- if the agent
    is killed outright, the OS closes the handle and every borrowed process
    goes with it. The POSIX path has no equivalent guarantee.
    """

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle
        self.cpu_capped = False
        """Whether the CPU rate control call actually succeeded. Tracked apart
        from memory because CPU rate control can fail on its own (it needs
        Windows 8+), and reporting a cap we did not set would be a lie."""
        self.priority_lowered = False

    @property
    def handle(self) -> int | None:
        return self._handle

    @classmethod
    def create(
        cls, ram_bytes: int, cpu_cores: int, logical_cpus: int
    ) -> WindowsJobObject | None:
        """A job with the limits already on it, or None if it could not be made.

        Never raises: a node that refuses to run anything because Job Objects
        were unavailable is worse than one that runs the job and says the caps
        are advisory.

        Note the ordering -- limits go on the *empty* job, before any process is
        assigned. Assigning first would leave a window in which the process is
        in an unrestricted job, and Win32 has no way to remove a process from a
        job to undo it. Until something is assigned, abandoning the handle costs
        nothing.
        """
        try:
            lib = _kernel32()
        except OSError as exc:
            _log.debug("no kernel32: %s", exc)
            return None

        handle = lib.CreateJobObjectW(None, None)
        if not handle:
            _log.debug("CreateJobObjectW failed (error %d)", _last_error())
            return None

        job = cls(int(handle))
        if not job._set_memory_limit(lib, ram_bytes, below_normal=True):
            job.close()
            return None
        job.priority_lowered = True
        job._set_cpu_limit(lib, ram_bytes, cpu_rate(cpu_cores, logical_cpus))
        return job

    def _set_memory_limit(
        self, lib: ctypes.CDLL, ram_bytes: int, *, below_normal: bool
    ) -> bool:
        info = extended_limit_info(ram_bytes, below_normal=below_normal)
        ok = lib.SetInformationJobObject(
            self._handle, JOB_INFO_EXTENDED_LIMIT, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            _log.debug("extended limit info failed (error %d)", _last_error())
        return bool(ok)

    def _set_cpu_limit(self, lib: ctypes.CDLL, ram_bytes: int, rate: int) -> None:
        """Best-effort: memory enforcement does not depend on this succeeding."""
        info = cpu_rate_info(rate)
        ok = lib.SetInformationJobObject(
            self._handle, JOB_INFO_CPU_RATE_CONTROL, ctypes.byref(info), ctypes.sizeof(info)
        )
        if ok:
            self.cpu_capped = True
            return

        # Some builds refuse CPU rate control alongside a priority-class limit.
        # Rather than guess which, drop the priority class and try once more --
        # a real CPU cap is worth more than a nice level.
        retryable = _last_error() == ERROR_INVALID_PARAMETER and self.priority_lowered
        if retryable and self._set_memory_limit(lib, ram_bytes, below_normal=False):
            self.priority_lowered = False
            retry = cpu_rate_info(rate)
            if lib.SetInformationJobObject(
                self._handle, JOB_INFO_CPU_RATE_CONTROL,
                ctypes.byref(retry), ctypes.sizeof(retry),
            ):
                self.cpu_capped = True
                return
        _log.debug("cpu rate control failed (error %d)", _last_error())

    def assign(self, pid: int) -> str | None:
        """Put a process in the job. Returns None on success, else why not.

        There is no PID-reuse race here: ``Popen`` holds a handle to the child
        for its whole lifetime, and Windows will not recycle a PID while any
        handle to the process object exists.
        """
        if self._handle is None:
            return "the job object was already closed"
        try:
            lib = _kernel32()
        except OSError as exc:
            return str(exc)

        process = lib.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            return f"OpenProcess failed (error {_last_error()})"
        try:
            if lib.AssignProcessToJobObject(self._handle, process):
                return None
            error = _last_error()
            if error == ERROR_ACCESS_DENIED:
                # Pre-Windows-8 only: nested jobs have been allowed since then,
                # and on a modern machine an outer job simply intersects with
                # ours, which is the behaviour we want.
                return "this agent is already inside a job object that forbids nesting"
            return f"AssignProcessToJobObject failed (error {error})"
        finally:
            # Not the job handle -- the process handle from OpenProcess. It has
            # no kill-on-close consequence to make the leak visible, so it has
            # to be closed deliberately.
            lib.CloseHandle(process)

    def terminate(self, exit_code: int = 1) -> bool:
        """Kill every process in the job, atomically."""
        if self._handle is None:
            return False
        try:
            return bool(_kernel32().TerminateJobObject(self._handle, exit_code))
        except OSError:
            return False

    def close(self) -> None:
        """Release the handle, killing anything still in the job.

        Idempotent. Deliberately not wired to ``__del__``: the handle is a plain
        int that nothing finalises, so forgetting to close it leaks a HANDLE --
        annoying. Wiring it to ``__del__`` would instead make a garbage
        collection pause able to kill a running job.
        """
        handle, self._handle = self._handle, None
        if handle is None:
            return
        with contextlib.suppress(OSError):
            _kernel32().CloseHandle(handle)
