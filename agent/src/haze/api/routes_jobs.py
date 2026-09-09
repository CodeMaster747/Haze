"""Dashboard endpoints for jobs.

Behind the loopback API's bearer token and origin check, like everything else.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Literal

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
from haze.scheduler.model import Decision, JobRequirement
from haze.transport import client as node_client

_log = log.get("api.jobs")

router = APIRouter()

# Strong references to in-flight remote submissions; a bare create_task can be
# garbage-collected mid-flight.
_background: set[asyncio.Task[None]] = set()


def _resolve_inputs(paths: list[str]) -> tuple[list[Path], int]:
    """Resolve every input and total their sizes, in one trip to the filesystem.

    The total is what the scheduler means by ``input_bytes`` -- the bytes that
    would have to reach a remote node and come back. Computed here rather than
    in a second pass because this function is already the one thread hop that
    stats these files, and asking the caller for a number it would have to
    derive the same way is how the two drift apart.
    """
    resolved = [Path(p).expanduser().resolve(strict=True) for p in paths]
    return resolved, sum(p.stat().st_size for p in resolved)


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
    placement: Literal["manual", "auto"] = "manual"
    """How the node is chosen.

    "manual" honours ``node_id`` below. "auto" asks the scheduler, which may
    well choose this machine anyway.

    A field of its own rather than a magic ``node_id`` value like "auto":
    ``node_id`` already carries two meanings (empty is here, anything else is
    that peer), and a node identity that is not a node identity is a value some
    future caller sends by accident. Being a Literal also means a typo is a 422
    naming the field rather than a silent fall-through to running it here.
    """
    node_id: str = ""
    """Empty means run here. Otherwise the paired peer to run it on."""
    work_units: float | None = Field(default=None, gt=0)
    """Rough compute size, when the caller knows better than the runtime.

    Overrides the runtime's own estimate on the auto path; ignored otherwise.
    One unit is one second on a node with speed_factor 1.0 -- the same scale
    /schedule takes, so a preview and the submission that follows it can be
    given identical inputs."""
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


async def _place(
    request: Request,
    agent: Agent,
    body: SubmitRequest,
    sources: list[Path],
    input_bytes: int,
) -> Decision:
    """Ask the scheduler where this job should run.

    The same three-line recipe /schedule uses -- probe, build candidates,
    decide -- with the two inputs a submission has and a preview does not:
    ``input_bytes`` totalled from the files being sent, and ``work_units``
    either given by the caller or estimated by the runtime itself.

    Capabilities come from the *cached* probe, not the live one. A preview is
    rare and deliberate and can afford four seconds of asking; a submission is
    something a user is waiting on.
    """
    capabilities = await cluster.cached_capabilities(agent.identity, agent.cfg)
    candidates = await cluster.build(
        request.app.state.hub.latest(), agent.node_id, agent.cfg.node_name, capabilities
    )
    if body.work_units is not None:
        # A caller that has measured this exact job knows more than a runtime
        # reasoning from its arguments, so an explicit hint always wins.
        work_units = body.work_units
    else:
        # The estimate may stat files or shell out to ffprobe, so it goes off
        # the event loop like the other filesystem work on this path.
        work_units = await asyncio.to_thread(
            runtimes.estimate_work_units, body.runtime, body.args, sources
        )
    return decide(
        candidates,
        JobRequirement(
            runtime=body.runtime,
            cpu_cores=body.cpu_cores,
            ram_bytes=body.ram_bytes,
            needs_gpu=body.needs_gpu,
            preferred_encoders=body.preferred_encoders,
            input_bytes=input_bytes,
            work_units=work_units,
        ),
    )


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
    if body.placement == "auto" and body.node_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "placement 'auto' chooses the node; do not also send a node_id",
        )

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
        sources, input_bytes = await asyncio.to_thread(_resolve_inputs, body.files)
    except OSError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"input file not found: {exc}") from exc

    target = body.node_id
    placement: dict[str, Any] | None = None

    if body.placement == "auto":
        decision = await _place(request, agent, body, sources, input_bytes)
        placement = decision.to_dict()
        if decision.chosen is None:
            # Decision.summary is already written for a person -- "no node can
            # run ffmpeg: laptop does not have ffmpeg; nas does not have
            # ffmpeg". Rewriting it here would be a second, worse copy of a
            # sentence the scheduler already got right.
            return JSONResponse(agent.executor.reject(spec, decision.summary, placement).to_dict())
        # cluster.build puts this node first with node_id == agent.node_id, so
        # comparing against it is what selects the local branch below.
        target = "" if decision.chosen == agent.node_id else decision.chosen

    if not target:
        # Local: copy inputs into the job directory so the runtime's path
        # allowlist has something to resolve against.
        if sources:
            await asyncio.to_thread(
                _stage_inputs, agent.executor.workdir_for(spec.job_id), sources
            )
        return JSONResponse(agent.executor.submit(spec, placement).to_dict())

    # Remote: run it on a paired peer and mirror its progress into this node's
    # job list, so the dashboard shows local and remote work in one place.
    mirror = agent.executor
    placeholder = mirror.submit_placeholder(spec, target, placement)

    async def run() -> None:
        try:
            final = await node_client.submit_job_to(
                target, spec, agent.identity, agent.cfg,
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
