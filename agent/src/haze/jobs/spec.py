"""What a job is.

Haze does not run arbitrary commands. A job names a **runtime** from a fixed
allowlist and supplies typed arguments; the runtime builds the argv. There is
no shell anywhere in the path, and no field a peer controls ever becomes a
command name.

That is a deliberate narrowing. "Run this shell command on my other machine" is
a more flexible product and a much worse one to defend: it makes every paired
node a remote shell, and the resource caps below would be the only thing
between a bug and a wiped disk. An allowlist means a peer can ask for a video
transcode or a Blender render, and cannot ask for anything else.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Any


class JobState(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    """Refused before starting -- unknown runtime, or over this peer's caps.
    Distinct from FAILED so "you asked for something I will not do" never looks
    like "your job crashed"."""

    @property
    def terminal(self) -> bool:
        return self in {
            JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.REJECTED
        }


@dataclass(frozen=True)
class ResourceRequest:
    """What a job asks for. Checked against the peer's caps before admission."""

    cpu_cores: int = 1
    ram_bytes: int = 1 << 30          # 1 GiB
    wall_seconds: int = 3600
    needs_gpu: bool = False
    preferred_encoders: list[str] = field(default_factory=list)
    """Hardware encoders that would make this job much faster. Not a
    requirement -- a node without them can still run the job, more slowly. The
    scheduler (M4) treats this as a strong preference."""


@dataclass(frozen=True)
class JobSpec:
    """A request to run something."""

    job_id: str
    runtime: str
    """Must name an entry in jobs.runtimes.REGISTRY."""
    args: dict[str, Any]
    """Runtime-specific, and validated by that runtime. Never a command line."""
    resources: ResourceRequest = field(default_factory=ResourceRequest)
    submitted_by: str = ""
    """Node ID of the requesting peer, or "" for a locally-submitted job."""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "runtime": self.runtime,
            "args": self.args,
            "label": self.label,
            "submitted_by": self.submitted_by,
            "resources": {
                "cpu_cores": self.resources.cpu_cores,
                "ram_bytes": self.resources.ram_bytes,
                "wall_seconds": self.resources.wall_seconds,
                "needs_gpu": self.resources.needs_gpu,
                "preferred_encoders": self.resources.preferred_encoders,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobSpec:
        raw = data.get("resources") or {}
        return cls(
            job_id=str(data["job_id"]),
            runtime=str(data["runtime"]),
            args=dict(data.get("args") or {}),
            label=str(data.get("label") or ""),
            submitted_by=str(data.get("submitted_by") or ""),
            resources=ResourceRequest(
                cpu_cores=int(raw.get("cpu_cores", 1)),
                ram_bytes=int(raw.get("ram_bytes", 1 << 30)),
                wall_seconds=int(raw.get("wall_seconds", 3600)),
                needs_gpu=bool(raw.get("needs_gpu", False)),
                preferred_encoders=list(raw.get("preferred_encoders") or []),
            ),
        )


@dataclass
class Progress:
    """Normalised progress, whatever the runtime.

    ffmpeg and Blender report progress in entirely different formats; both are
    parsed into this so the dashboard has one shape to render and the scheduler
    one shape to reason about.
    """

    fraction: float | None = None
    """0.0-1.0 where the runtime gives enough to compute it, else None. A
    progress bar that lies is worse than one that admits it does not know."""
    stage: str = ""
    detail: str = ""
    frames_done: int | None = None
    frames_total: int | None = None
    rate: str = ""
    """Human-readable throughput, e.g. "142 fps" or "3.4x"."""
    eta_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fraction": self.fraction,
            "stage": self.stage,
            "detail": self.detail,
            "frames_done": self.frames_done,
            "frames_total": self.frames_total,
            "rate": self.rate,
            "eta_seconds": self.eta_seconds,
        }


@dataclass
class JobRecord:
    """A job's full state, as this node knows it."""

    spec: JobSpec
    state: JobState = JobState.QUEUED
    progress: Progress = field(default_factory=Progress)
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    exit_code: int | None = None
    error: str = ""
    log_tail: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    peak_ram_bytes: int = 0
    enforcement: dict[str, Any] | None = None
    """What the OS was actually made to enforce for this job, from
    ``limits.Enforcement.to_dict()``.

    A field rather than only the ``[haze] caps:`` line in ``log_tail``, for the
    same reason ``placement`` is one: ``JobExecutor.update_remote`` replaces
    ``log_tail`` wholesale with the peer's own, so for a job running on someone
    else's machine the caps line survives only until it scrolls out of the
    200-line window. A remote job is precisely the case where you cannot go and
    inspect the machine yourself, so it is the wrong record to lose."""

    placement: dict[str, Any] | None = None
    """The scheduler's Decision, when this job was placed automatically.

    A field of its own rather than a line in ``log_tail``: a remote job's
    ``log_tail`` is replaced wholesale by the peer's own (see
    ``JobExecutor.update_remote``), so reasoning written there is erased by the
    first progress update to arrive -- which is precisely the case where "why
    did it go *there*?" is worth being able to answer.

    Kept as a plain dict (``Decision.to_dict()``, filled in by the API) rather
    than the dataclass, so this module stays free of a dependency on the
    scheduler package it is otherwise entirely independent of.
    """

    @property
    def duration_s(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or dt.datetime.now(dt.UTC)
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.spec.to_dict(),
            "state": self.state.value,
            "progress": self.progress.to_dict(),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_s": round(self.duration_s, 2) if self.duration_s is not None else None,
            "exit_code": self.exit_code,
            "error": self.error,
            "log_tail": self.log_tail[-40:],
            "outputs": self.outputs,
            "peak_ram_bytes": self.peak_ram_bytes,
            "enforcement": self.enforcement,
            "placement": self.placement,
        }
