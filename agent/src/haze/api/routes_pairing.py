"""Dashboard endpoints for pairing and peer management.

All of these sit behind the loopback API's bearer token and origin check --
they are only reachable from the console on this machine.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from haze import log
from haze.db import peers as peer_db
from haze.identity import nodeid
from haze.pairing.manager import ARM_TTL_S
from haze.runtime import Agent
from haze.transport import client as node_client
from haze.transport.handshake import PeerIdentity

_log = log.get("api.pairing")

router = APIRouter()

# Strong references to in-flight pairing tasks; see initiate().
_background: set[asyncio.Task[None]] = set()


def _agent(request: Request) -> Agent:
    agent: Agent | None = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent is still starting")
    return agent


class ArmRequest(BaseModel):
    ttl_s: float = Field(default=ARM_TTL_S, ge=10, le=900)


class DecisionRequest(BaseModel):
    session_id: str


class PairRequest(BaseModel):
    host: str
    port: int = Field(default=0, ge=0, le=65535)


@router.get("/pairing")
async def pairing_state(request: Request) -> JSONResponse:
    return JSONResponse(_agent(request).pairing.state())


@router.post("/pairing/arm")
async def arm(request: Request, body: ArmRequest) -> JSONResponse:
    agent = _agent(request)
    agent.pairing.arm(body.ttl_s)
    return JSONResponse(agent.pairing.state())


@router.post("/pairing/disarm")
async def disarm(request: Request) -> JSONResponse:
    agent = _agent(request)
    agent.pairing.disarm()
    return JSONResponse(agent.pairing.state())


@router.post("/pairing/confirm")
async def confirm(request: Request, body: DecisionRequest) -> JSONResponse:
    if not _agent(request).pairing.confirm(body.session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such pending pairing, or it expired")
    return JSONResponse({"ok": True})


@router.post("/pairing/reject")
async def reject(request: Request, body: DecisionRequest) -> JSONResponse:
    if not _agent(request).pairing.reject(body.session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such pending pairing, or it expired")
    return JSONResponse({"ok": True})


@router.get("/peers")
async def list_peers(request: Request) -> JSONResponse:
    agent = _agent(request)
    rows = await peer_db.all_peers()
    return JSONResponse(
        {
            "self": {
                "node_id": agent.node_id,
                "short_id": agent.identity.short_id,
                "name": agent.cfg.node_name,
            },
            "peers": [
                {
                    "node_id": p.node_id,
                    "short_id": nodeid.short(p.node_id),
                    "name": p.display_name,
                    "platform": p.platform,
                    "version": p.agent_version,
                    "last_host": p.last_host,
                    "last_port": p.last_port,
                    "paired_at": p.paired_at.isoformat(),
                    "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
                }
                for p in rows
            ],
        }
    )


@router.delete("/peers/{node_id}")
async def unpair(node_id: str) -> JSONResponse:
    if not await peer_db.remove(node_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not paired with that node")
    return JSONResponse({"ok": True})


@router.post("/peers/{node_id}/ping")
async def ping(request: Request, node_id: str) -> JSONResponse:
    agent = _agent(request)
    ok, detail = await node_client.ping_peer(node_id, agent.identity, agent.cfg)
    return JSONResponse({"ok": ok, "detail": detail})


@router.post("/pairing/initiate")
async def initiate(request: Request, body: PairRequest) -> JSONResponse:
    """Start pairing with a node, from the dashboard.

    Returns immediately. The actual pairing runs as a background task, because
    the flow blocks on a human walking to the other machine -- holding an HTTP
    request open for two minutes would hit every proxy and browser timeout in
    between for no benefit.

    Progress reaches the browser through the pairing state the task publishes:
    once the SAS is known it appears in GET /pairing as a pending request with
    direction "outgoing", and the user confirms it exactly as they would an
    incoming one.
    """
    agent = _agent(request)
    port = body.port or agent.cfg.node_port

    async def confirm(digits: str, words: list[str], peer: PeerIdentity) -> bool:
        # Publishing the request is what makes the digits visible in the UI.
        pending = agent.pairing.open_request(peer, direction="outgoing")
        # The SAS the manager derived must equal the one the client computed;
        # they use the same inputs, so a mismatch would mean a bug rather than
        # an attack -- but silently showing two different numbers on one screen
        # is exactly the failure that would destroy trust in the mechanism.
        if pending.sas_digits != digits:  # pragma: no cover - defensive
            _log.error("internal SAS mismatch: %s vs %s", pending.sas_digits, digits)
            agent.pairing.reject(pending.session_id)
            return False
        decision = await agent.pairing.wait_for_decision(pending.session_id)
        return decision == "confirmed"

    async def run() -> None:
        try:
            peer = await node_client.pair(
                body.host, port, agent.identity, agent.cfg.node_name,
                agent.cfg.node_port, confirm,
            )
            _log.info("paired with %s via the dashboard", peer.display_name)
        except node_client.ConnectError as exc:
            _log.warning("dashboard pairing with %s failed: %s", body.host, exc)
            agent.pairing.set_last_error(str(exc))
        except Exception as exc:
            _log.exception("dashboard pairing with %s crashed", body.host)
            agent.pairing.set_last_error(str(exc))

    agent.pairing.clear_last_error()
    task = asyncio.create_task(run())
    # Hold a reference: a bare create_task can be garbage-collected mid-flight.
    _background.add(task)
    task.add_done_callback(_background.discard)

    return JSONResponse({"started": True, "host": body.host, "port": port})


__all__ = ["router"]
