"""Dashboard endpoints for jobs.

Behind the loopback API's bearer token and origin check, like everything else.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from haze import log
from haze.jobs import runtimes
from haze.jobs.executor import new_job_id
from haze.jobs.spec import JobSpec, ResourceRequest
from haze.runtime import Agent
from haze.scheduler import cluster
from haze.scheduler.decide import decide
from haze.scheduler.model import JobRequirement
from haze.transport import client as node_client

_log = log.get("api.jobs")

router = APIRouter()

# Strong references to in-flight remote submissions; a bare create_task can be
# garbage-collected mid-flight.
_background: set[asyncio.Task[None]] = set()


def _resolve_inputs(paths: list[str]) -> list[Path]:
    return [Path(p).expanduser().resolve(strict=True) for p in paths]


def _stage_inputs(workdir: Path, sources: list[Path]) -> None:
    """Copy a local job's inputs into its directory, so the runtime's path
    allowlist has something inside the sandbox to resolve against."""
    workdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for source in sources:
        shutil.copy(source, workdir / source.name)


def _agent(request: Request) -> Agent:
    agent: Agent | None = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent is still starting")
    return agent


class SubmitRequest(BaseModel):
    runtime: str
    args: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    node_id: str = ""
    """Empty means run here. Otherwise the paired peer to run it on."""
    cpu_cores: int = Field(default=1, ge=1, le=256)
    ram_bytes: int = Field(default=1 << 30, ge=1 << 20)
    wall_seconds: int = Field(default=3600, ge=1, le=86400)
    needs_gpu: bool = False
    preferred_encoders: list[str] = Field(default_factory=list)
    fetch_outputs: bool = True
    """Bring a remote job's outputs back here when it finishes.

    Default on, because "get the result back" is the whole point. Can be
    turned off for a job whose output is large and better left where it was
    produced."""
    files: list[str] = Field(default_factory=list)
    """Absolute paths on THIS machine to stage into the job's directory.

    Local paths, not uploads: the dashboard and CLI both run on the same
    machine as the agent, so there is no reason to push bytes through the
    browser. For a remote job these are read here and streamed to the peer."""


@router.get("/jobs")
async def list_jobs(request: Request) -> JSONResponse:
    return JSONResponse(_agent(request).executor.state())


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> JSONResponse:
    record = _agent(request).executor.get(job_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job")
    return JSONResponse(record.to_dict())


@router.post("/jobs")
async def submit(request: Request, body: SubmitRequest) -> JSONResponse:
    agent = _agent(request)
    spec = JobSpec(
        job_id=new_job_id(),
        runtime=body.runtime,
        args=body.args,
        label=body.label,
        resources=ResourceRequest(
            cpu_cores=body.cpu_cores,
            ram_bytes=body.ram_bytes,
            wall_seconds=body.wall_seconds,
            needs_gpu=body.needs_gpu,
            preferred_encoders=body.preferred_encoders,
        ),
    )

    try:
        # ASYNC240 flags blocking filesystem calls in async handlers. These are
        # local stat() calls on a handful of paths -- microseconds, on loopback,
        # from a single-user dashboard. Pulling in anyio.Path to avoid them
        # would add a dependency and obscure the code for no measurable gain.
        sources = await asyncio.to_thread(_resolve_inputs, body.files)
    except OSError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"input file not found: {exc}") from exc

    if not body.node_id:
        # Local: copy inputs into the job directory so the runtime's path
        # allowlist has something to resolve against.
        if sources:
            await asyncio.to_thread(
                _stage_inputs, agent.executor.workdir_for(spec.job_id), sources
            )
        return JSONResponse(agent.executor.submit(spec).to_dict())

    # Remote: run it on a paired peer and mirror its progress into this node's
    # job list, so the dashboard shows local and remote work in one place.
    mirror = agent.executor
    placeholder = mirror.submit_placeholder(spec, body.node_id)

    async def run() -> None:
        try:
            final = await node_client.submit_job_to(
                body.node_id, spec, agent.identity, agent.cfg,
                on_progress=lambda payload: mirror.update_remote(spec.job_id, payload),
                files=sources,
                fetch_into=(
                    agent.executor.workdir_for(spec.job_id) / "out"
                    if body.fetch_outputs
                    else None
                ),
            )
            mirror.update_remote(spec.job_id, final)
        except node_client.ConnectError as exc:
            mirror.fail_remote(spec.job_id, str(exc))
        except Exception as exc:
            _log.exception("remote job %s crashed", spec.job_id[:8])
            mirror.fail_remote(spec.job_id, str(exc))

    task = asyncio.create_task(run())
    _background.add(task)
    task.add_done_callback(_background.discard)

    return JSONResponse(placeholder.to_dict())


@router.post("/jobs/{job_id}/cancel")
async def cancel(request: Request, job_id: str) -> JSONResponse:
    if not await _agent(request).executor.cancel(job_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such job, or it already finished")
    return JSONResponse({"ok": True})


@router.delete("/jobs/{job_id}")
async def cleanup(request: Request, job_id: str) -> JSONResponse:
    if not _agent(request).executor.cleanup(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "job is still running")
    return JSONResponse({"ok": True})


class ScheduleRequest(BaseModel):
    runtime: str
    cpu_cores: int = Field(default=1, ge=1, le=256)
    ram_bytes: int = Field(default=1 << 30, ge=1 << 20)
    needs_gpu: bool = False
    preferred_encoders: list[str] = Field(default_factory=list)
    input_bytes: int = Field(default=0, ge=0)
    work_units: float = Field(default=1.0, gt=0)


@router.post("/schedule")
async def schedule(request: Request, body: ScheduleRequest) -> JSONResponse:
    """Where would this job go, and why?

    A preview: it decides but does not submit. This is what `haze explain`
    prints and what the dashboard's decision trace shows -- the point being
    that the reasoning is inspectable before you commit to it, not archaeology
    afterwards.
    """
    agent = _agent(request)
    hub = request.app.state.hub
    # Asked live rather than cached: a placement preview is user-initiated
    # and rare, and a stale view of what a peer can run is exactly the kind
    # of wrong that makes a scheduler untrustworthy.
    capabilities = await cluster.probe_peers(agent.identity, agent.cfg)
    candidates = await cluster.build(
        hub.latest(), agent.node_id, agent.cfg.node_name, capabilities
    )
    decision = decide(
        candidates,
        JobRequirement(
            runtime=body.runtime,
            cpu_cores=body.cpu_cores,
            ram_bytes=body.ram_bytes,
            needs_gpu=body.needs_gpu,
            preferred_encoders=body.preferred_encoders,
            input_bytes=body.input_bytes,
            work_units=body.work_units,
        ),
    )
    return JSONResponse(decision.to_dict())


@router.get("/runtimes")
async def list_runtimes(request: Request) -> JSONResponse:
    agent = _agent(request)
    return JSONResponse(
        {
            "available": runtimes.available_names(),
            "all": [
                {"name": name, "available": rt.available(), "description": rt.description}
                for name, rt in sorted(runtimes.REGISTRY.items())
            ],
            "caps": agent.executor.caps.to_dict(),
        }
    )
