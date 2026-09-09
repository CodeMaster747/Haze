"""Dashboard endpoints for pairing and peer management.

All of these sit behind the loopback API's bearer token and origin check --
they are only reachable from the console on this machine.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from haze import config, log
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


@router.get("/discovery")
async def discovery_state(request: Request) -> JSONResponse:
    """Everything this node currently believes is on the network."""
    agent = _agent(request)
    if agent.discovery is None:
        return JSONResponse({"mdns": False, "broadcast": False, "nodes": []})
    return JSONResponse(agent.discovery.state())


class ManualNodeRequest(BaseModel):
    host: str
    port: int = Field(default=0, ge=0, le=65535)


@router.post("/discovery/manual")
async def add_manual(request: Request, body: ManualNodeRequest) -> JSONResponse:
    """Add a node by address.

    Always available, never hidden behind a "discovery failed" state: on a
    guest SSID with client isolation no discovery mechanism can work, and the
    user needs a path in that does not depend on one.
    """
    agent = _agent(request)
    if agent.discovery is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "discovery is disabled")
    agent.discovery.add_manual(body.host, body.port or agent.cfg.node_port)
    return JSONResponse(agent.discovery.state())


async def _check_resolvable(host: str, port: int) -> None:
    """Reject an address that does not resolve, at the moment it is typed.

    Not politeness. `asyncio.open_connection` resolves on the default thread
    pool, and cancelling the await does not free the thread that is blocked in
    getaddrinfo. A pinned name that never resolves gets re-dialled by the
    scheduler's capability probe on a timer, and the stuck threads accumulate
    until the pool is exhausted -- at which point unrelated `to_thread` calls
    across the agent stall. One bounded lookup here costs a moment and turns
    that into an error message.
    """
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(loop.getaddrinfo(host, port), 5.0)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{host} does not resolve from this machine, so it could never be dialled.",
        ) from exc


class PinAddressRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=0, ge=0, le=65535)


@router.put("/peers/{node_id}/address")
async def pin_address(request: Request, node_id: str, body: PinAddressRequest) -> JSONResponse:
    """Pin the address to reach a peer at.

    Inbound sessions rewrite a peer's last-seen address on every connection, so
    on a machine reachable both on the LAN and over an overlay network the
    recorded address flip-flops. A pin is not overwritten by observed traffic.
    """
    agent = _agent(request)
    host = body.host.strip()

    peer = await peer_db.get(node_id)
    if peer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not paired with that node")

    # The peer's port, never this node's. `cfg.node_port` is what *we* listen
    # on, and defaulting to it is how a node ends up dialling itself -- the
    # same mistake the handshake's port advertisement was added to fix. Prefer
    # the port the peer is known to listen on, and fall back to the well-known
    # default rather than to anything local.
    port = body.port or peer.last_port or config.DEFAULT_NODE_PORT

    await _check_resolvable(host, port)
    if not await peer_db.pin_address(node_id, host, port):  # pragma: no cover - checked above
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not paired with that node")

    # Feed it to discovery too, where manual entries are deliberately exempt
    # from the staleness sweep -- otherwise a peer that is off-LAN and so never
    # advertises simply vanishes from the dashboard.
    if agent.discovery is not None:
        agent.discovery.add_manual(host, port, node_id=node_id)
    return JSONResponse({"ok": True, "host": host, "port": port})


@router.delete("/peers/{node_id}/address")
async def clear_address(node_id: str) -> JSONResponse:
    if not await peer_db.clear_address(node_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not paired with that node")
    return JSONResponse({"ok": True})


@router.get("/peers")
async def list_peers(request: Request) -> JSONResponse:
    agent = _agent(request)
    rows = await peer_db.all_peers()
    pins = await peer_db.all_pins()
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
                    # The dashboard and every CLI resolver read this dict, so
                    # the pin has to appear here or the UI keeps showing an
                    # address the agent is no longer dialling.
                    "pinned_host": pins[p.node_id][0].host if pins.get(p.node_id) else "",
                    "pinned_port": pins[p.node_id][0].port if pins.get(p.node_id) else 0,
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
