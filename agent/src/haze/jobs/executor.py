"""Running jobs, and stopping them.

One subprocess per job, in its own directory, in its own process group. The
executor owns the wall clock and the memory watch: whatever the OS will or will
not enforce (see limits.py), a job that overruns is killed here.

Cancellation and timeout signal the *process group*, not the process. Both
ffmpeg and Blender spawn helpers, and killing only the parent leaves those
running and holding the resources the cap was about.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import os
import shutil
import signal
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from haze import config, log
from haze.jobs import limits, runtimes
from haze.jobs.spec import JobRecord, JobSpec, JobState

_log = log.get("jobs.executor")

LOG_TAIL_LINES = 200
MEMORY_POLL_S = 0.5
PROGRESS_PUBLISH_S = 0.4
"""Progress is coalesced to this interval. ffmpeg emits a block several times a
second; forwarding each one would spend more effort on the dashboard than on
the job."""

RETAIN_FINISHED = 40
"""How many finished jobs to keep.

Beyond this, the oldest are forgotten and their directories deleted. Without a
limit an agent left running accumulates job records, completed asyncio Task
objects, and -- worst -- every job's working directory, which for a render job
holds all its output frames. An agent should not quietly fill a disk because it
was left on."""

OnUpdate = Callable[[JobRecord], None]


class Caps:
    """What a given submitter is allowed to ask for on this node."""

    def __init__(self, max_cores: int, max_ram_bytes: int, max_wall_seconds: int,
                 allow_gpu: bool = True) -> None:
        self.max_cores = max_cores
        self.max_ram_bytes = max_ram_bytes
        self.max_wall_seconds = max_wall_seconds
        self.allow_gpu = allow_gpu

    def reject_reason(self, spec: JobSpec) -> str | None:
        r = spec.resources
        if r.cpu_cores > self.max_cores:
            return f"asked for {r.cpu_cores} cores; this node allows {self.max_cores}"
        if r.ram_bytes > self.max_ram_bytes:
            return (f"asked for {r.ram_bytes // 2**30} GiB of memory; this node allows "
                    f"{self.max_ram_bytes // 2**30} GiB")
        if r.wall_seconds > self.max_wall_seconds:
            return (f"asked for {r.wall_seconds}s of runtime; this node allows "
                    f"{self.max_wall_seconds}s")
        if r.needs_gpu and not self.allow_gpu:
            return "asked for the GPU; this node does not share it"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cores": self.max_cores,
            "max_ram_bytes": self.max_ram_bytes,
            "max_wall_seconds": self.max_wall_seconds,
            "allow_gpu": self.allow_gpu,
            "enforcement": limits.describe_platform(),
        }


def default_caps() -> Caps:
    """Conservative defaults: half the machine.

    A node that lends out everything it has is a node whose owner turns Haze
    off the first time their laptop stutters.
    """
    total_ram = psutil.virtual_memory().total
    cores = psutil.cpu_count(logical=True) or 2
    return Caps(
        max_cores=max(1, cores // 2),
        max_ram_bytes=total_ram // 2,
        max_wall_seconds=2 * 3600,
    )


class JobExecutor:
    """Owns every job this node is running."""

    def __init__(self, on_update: OnUpdate | None = None, caps: Caps | None = None) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._on_update = on_update
        self.caps = caps or default_caps()
        self.retain_finished = RETAIN_FINISHED

    # --- introspection -----------------------------------------------------

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def all_jobs(self) -> list[JobRecord]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def state(self) -> dict[str, Any]:
        return {
            "caps": self.caps.to_dict(),
            "runtimes": [
                {"name": name, "available": rt.available(), "description": rt.description}
                for name, rt in sorted(runtimes.REGISTRY.items())
            ],
            "jobs": [j.to_dict() for j in self.all_jobs()[:50]],
        }

    # --- submission --------------------------------------------------------

    def workdir_for(self, job_id: str) -> Path:
        return config.state_dir() / "jobs" / job_id

    def submit(self, spec: JobSpec) -> JobRecord:
        """Admit or reject a job. Never raises for a bad request -- a rejection
        is a job record with a reason, so the submitter always gets an answer
        in the same shape."""
        self._prune()
        record = JobRecord(spec=spec)
        self._jobs[spec.job_id] = record

        reason = self.caps.reject_reason(spec)
        if reason is not None:
            return self._reject(record, reason)

        try:
            runtime = runtimes.get(spec.runtime)
        except runtimes.JobArgumentError as exc:
            return self._reject(record, str(exc))

        if not runtime.available():
            return self._reject(record, f"{spec.runtime} is not installed on this node")

        self._tasks[spec.job_id] = asyncio.create_task(
            self._run(record, runtime), name=f"haze-job-{spec.job_id[:8]}"
        )
        self._publish(record)
        return record

    def _reject(self, record: JobRecord, reason: str) -> JobRecord:
        record.state = JobState.REJECTED
        record.error = reason
        record.finished_at = dt.datetime.now(dt.UTC)
        _log.info("rejected job %s: %s", record.spec.job_id[:8], reason)
        self._publish(record)
        self._prune()
        return record

    # --- remote mirroring --------------------------------------------------
    # A job running on another machine still appears in this node's list, so
    # the dashboard shows local and remote work together rather than making the
    # user hold "where did I send that?" in their head.

    def submit_placeholder(self, spec: JobSpec, node_id: str) -> JobRecord:
        record = JobRecord(spec=spec, state=JobState.QUEUED)
        record.log_tail.append(f"[haze] submitted to {node_id.split('-')[0]}")
        self._jobs[spec.job_id] = record
        self._publish(record)
        return record

    def update_remote(self, job_id: str, payload: dict[str, Any]) -> None:
        """Fold a remote node's job record into the local mirror."""
        record = self._jobs.get(job_id)
        if record is None:
            return
        with contextlib.suppress(KeyError, ValueError, TypeError):
            record.state = JobState(payload["state"])
        progress = payload.get("progress") or {}
        record.progress.fraction = progress.get("fraction")
        record.progress.stage = str(progress.get("stage") or "")
        record.progress.detail = str(progress.get("detail") or "")
        record.progress.frames_done = progress.get("frames_done")
        record.progress.frames_total = progress.get("frames_total")
        record.progress.rate = str(progress.get("rate") or "")
        record.progress.eta_seconds = progress.get("eta_seconds")
        record.exit_code = payload.get("exit_code")
        record.error = str(payload.get("error") or "")
        record.outputs = list(payload.get("outputs") or [])
        record.peak_ram_bytes = int(payload.get("peak_ram_bytes") or 0)
        tail = payload.get("log_tail")
        if isinstance(tail, list):
            record.log_tail = [str(line) for line in tail][-LOG_TAIL_LINES:]
        if record.started_at is None and record.state is not JobState.QUEUED:
            record.started_at = dt.datetime.now(dt.UTC)
        if record.state.terminal and record.finished_at is None:
            record.finished_at = dt.datetime.now(dt.UTC)
        self._publish(record)

    def fail_remote(self, job_id: str, reason: str) -> None:
        record = self._jobs.get(job_id)
        if record is None or record.state.terminal:
            return
        record.state = JobState.FAILED
        record.error = reason
        record.finished_at = dt.datetime.now(dt.UTC)
        self._publish(record)

    async def cancel(self, job_id: str) -> bool:
        record = self._jobs.get(job_id)
        if record is None or record.state.terminal:
            return False
        record.state = JobState.CANCELLED
        await self._terminate(job_id)
        return True

    # --- execution ---------------------------------------------------------

    async def _run(self, record: JobRecord, runtime: runtimes.Runtime) -> None:
        spec = record.spec
        workdir = self.workdir_for(spec.job_id)
        workdir.mkdir(mode=0o700, parents=True, exist_ok=True)

        try:
            prepared = runtime.prepare(spec.args, workdir)
        except runtimes.JobArgumentError as exc:
            self._reject(record, str(exc))
            return

        argv, enforcement = limits.wrap_command(
            prepared.argv, spec.resources.ram_bytes, spec.resources.cpu_cores
        )
        if not enforcement.fully_enforced:
            # Surfaced on the job itself, not only in documentation: the person
            # deciding whether to accept work needs it in front of them.
            record.log_tail.append(f"[haze] caps: {'; '.join(enforcement.notes)}")

        record.state = JobState.RUNNING
        record.started_at = dt.datetime.now(dt.UTC)
        self._publish(record)
        _log.info("running job %s (%s)", spec.job_id[:8], spec.runtime)

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=prepared.cwd,
                stdout=asyncio.subprocess.PIPE,
                # Merged: ffmpeg writes progress to stdout and its log to
                # stderr, and we want both in the tail. Parsers ignore lines
                # they do not recognise.
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, **prepared.env},
                preexec_fn=limits.preexec_for(
                    spec.resources.ram_bytes, spec.resources.wall_seconds
                ),
            )
        except (OSError, ValueError) as exc:
            record.state = JobState.FAILED
            record.error = f"could not start: {exc}"
            record.finished_at = dt.datetime.now(dt.UTC)
            self._publish(record)
            return

        self._processes[spec.job_id] = process
        watchdog = asyncio.create_task(self._watch(record, process))
        try:
            await self._pump(record, process, prepared)
            record.exit_code = await process.wait()
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
            self._processes.pop(spec.job_id, None)

        self._finish(record, prepared)

    async def _pump(self, record: JobRecord, process: asyncio.subprocess.Process,
                    prepared: runtimes.Prepared) -> None:
        """Read output, feed the parser, publish at a sane rate."""
        assert process.stdout is not None
        last_published = 0.0

        while True:
            try:
                raw = await process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                # A single absurdly long line (a progress bar without newlines).
                # Skip it rather than killing the job.
                continue
            if not raw:
                break

            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            record.log_tail.append(line)
            if len(record.log_tail) > LOG_TAIL_LINES:
                del record.log_tail[:-LOG_TAIL_LINES]

            if prepared.parser.feed(line):
                record.progress = prepared.parser.progress
                now = time.monotonic()
                if now - last_published >= PROGRESS_PUBLISH_S:
                    last_published = now
                    self._publish(record)

    async def _watch(self, record: JobRecord, process: asyncio.subprocess.Process) -> None:
        """Wall clock and memory. The executor enforces these regardless of what
        the OS is willing to."""
        deadline = time.monotonic() + record.spec.resources.wall_seconds
        limit = record.spec.resources.ram_bytes

        # Sample once straight away: a job that finishes inside the first poll
        # interval would otherwise report a peak of zero.
        record.peak_ram_bytes = max(record.peak_ram_bytes, _tree_rss(process.pid))

        while True:
            await asyncio.sleep(MEMORY_POLL_S)

            if time.monotonic() > deadline:
                record.state = JobState.FAILED
                record.error = f"exceeded its {record.spec.resources.wall_seconds}s time limit"
                await self._terminate(record.spec.job_id)
                return

            rss = _tree_rss(process.pid)
            record.peak_ram_bytes = max(record.peak_ram_bytes, rss)
            if rss > limit:
                # On macOS this is the only memory enforcement there is.
                record.state = JobState.FAILED
                record.error = (
                    f"exceeded its memory cap ({rss // 2**20} MiB used, "
                    f"{limit // 2**20} MiB allowed)"
                )
                await self._terminate(record.spec.job_id)
                return

    async def _terminate(self, job_id: str) -> None:
        process = self._processes.get(job_id)
        if process is None or process.returncode is not None:
            return
        # Signal the group: ffmpeg and Blender both spawn helpers that survive
        # a kill aimed at the parent alone.
        for sig, wait_s in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(os.getpgid(process.pid), sig)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), wait_s)
                return

    def _finish(self, record: JobRecord, prepared: runtimes.Prepared) -> None:
        record.finished_at = dt.datetime.now(dt.UTC)

        if prepared.outputs_from == "parser":
            record.outputs = list(getattr(prepared.parser, "saved_files", []))
            peak = int(getattr(prepared.parser, "peak_mem_bytes", 0))
            record.peak_ram_bytes = max(record.peak_ram_bytes, peak)
        else:
            record.outputs = [str(p) for p in prepared.explicit_outputs if p.exists()]

        if record.state in {JobState.CANCELLED, JobState.FAILED}:
            pass  # a reason was already recorded
        elif record.exit_code == 0:
            record.state = JobState.SUCCEEDED
            # Mutate rather than replace: the final rate ("412 MiB/s",
            # "3.4x realtime") is the number a benchmark exists to produce, and
            # building a fresh Progress here silently discarded it.
            record.progress.fraction = 1.0
            record.progress.stage = "done"
            record.progress.eta_seconds = 0.0
        else:
            record.state = JobState.FAILED
            record.error = _describe_exit(record.exit_code, record.log_tail)

        _log.info(
            "job %s %s in %.1fs", record.spec.job_id[:8], record.state.value,
            record.duration_s or 0.0,
        )
        self._publish(record)
        self._prune()

    # --- housekeeping ------------------------------------------------------

    def _publish(self, record: JobRecord) -> None:
        if self._on_update is not None:
            self._on_update(record)

    def _prune(self) -> None:
        """Forget old finished jobs, and delete their directories.

        Only finished ones, and only beyond the retention count -- a running
        job is never touched however old it is.
        """
        self._tasks = {
            job_id: task for job_id, task in self._tasks.items() if not task.done()
        }

        finished = sorted(
            (r for r in self._jobs.values() if r.state.terminal),
            key=lambda r: r.finished_at or r.created_at,
            reverse=True,
        )
        for record in finished[self.retain_finished :]:
            job_id = record.spec.job_id
            self._jobs.pop(job_id, None)
            shutil.rmtree(self.workdir_for(job_id), ignore_errors=True)
            _log.debug("pruned job %s", job_id[:8])

    async def shutdown(self) -> None:
        for job_id in list(self._processes):
            await self._terminate(job_id)
        for task in self._tasks.values():
            task.cancel()

    def cleanup(self, job_id: str) -> bool:
        """Delete one finished job's directory, on request."""
        record = self._jobs.get(job_id)
        if record is None or not record.state.terminal:
            return False
        shutil.rmtree(self.workdir_for(job_id), ignore_errors=True)
        self._jobs.pop(job_id, None)
        self._tasks.pop(job_id, None)
        return True

    def sweep_orphaned_dirs(self) -> int:
        """Delete job directories with no corresponding record.

        Runs at startup: an agent that was killed mid-job leaves its working
        directory behind, and nothing else would ever remove it.
        """
        root = config.state_dir() / "jobs"
        if not root.is_dir():
            return 0
        removed = 0
        for path in root.iterdir():
            if path.is_dir() and path.name not in self._jobs:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        if removed:
            _log.info("removed %d orphaned job director%s",
                      removed, "y" if removed == 1 else "ies")
        return removed


def _describe_exit(exit_code: int | None, log_tail: list[str]) -> str:
    """Turn an exit status into something a human can act on.

    A negative code means the process was killed by that signal, and the raw
    number is meaningless to anyone who does not have signal(7) memorised.
    SIGXCPU in particular is not a crash -- it is the CPU rlimit doing exactly
    what it was set up to do, and reporting it as "exited with code -24" makes
    a working safety limit look like a bug.
    """
    if exit_code is not None and exit_code < 0:
        signum = -exit_code
        known = {
            signal.SIGXCPU: "exceeded its CPU time limit (killed by the kernel)",
            signal.SIGKILL: "was killed (SIGKILL) -- usually a memory limit or a manual stop",
            signal.SIGTERM: "was asked to stop (SIGTERM)",
            signal.SIGSEGV: "crashed with a segmentation fault",
            signal.SIGABRT: "aborted",
        }
        described = known.get(signal.Signals(signum), f"was killed by signal {signum}")
        return f"{described}."

    tail = " | ".join(log_tail[-3:])
    return f"exited with code {exit_code}. {tail}".strip()


def new_job_id() -> str:
    # uuid4 rather than a counter: job ids travel between machines, and two
    # nodes must never mint the same one.
    return uuid.uuid4().hex


def _tree_rss(pid: int) -> int:
    """Resident memory of a process and everything it spawned.

    Summing the tree matters: Blender and ffmpeg both fork helpers, and
    measuring only the parent would let a job use several times its cap while
    reporting well under it.
    """
    try:
        parent = psutil.Process(pid)
        total = parent.memory_info().rss
        for child in parent.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                total += child.memory_info().rss
        return int(total)
    except psutil.Error:
        return 0
