"""Building the scheduler's input from what this agent actually knows.

Kept separate from `decide` on purpose: this half touches the database, the
telemetry hub and the peer table, and the moment any of that leaks into the
scoring the function stops being pure -- and the TypeScript mirror stops being
checkable against it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from haze import log
from haze.db import peers as peer_db
from haze.jobs import runtimes
from haze.scheduler.model import NodeCandidate

_log = log.get("scheduler.cluster")

# What we assume about a peer we have not measured. Pessimistic on purpose:
# over-estimating a link makes the scheduler ship work somewhere it should not.
ASSUMED_PEER_SPEED = 1.0
ASSUMED_PEER_THROUGHPUT_MBPS = 100.0
ASSUMED_PEER_LATENCY_MS = 3.0


async def probe_peers(identity: Any, cfg: Any, timeout_s: float = 4.0) -> dict[str, dict[str, Any]]:
    """Ask every paired peer what it can run, concurrently.

    Failures are not errors: a peer that is asleep or unreachable simply has no
    entry, and :func:`build` falls back to the pessimistic assumptions above.
    Placement should degrade to a guess rather than fail outright.
    """
    from haze.transport import client as node_client

    peers = await peer_db.all_peers()
    if not peers:
        return {}

    async def ask(node_id: str) -> tuple[str, dict[str, Any] | None]:
        try:
            return node_id, await asyncio.wait_for(
                node_client.peer_capabilities(node_id, identity, cfg), timeout_s
            )
        except (node_client.ConnectError, TimeoutError, OSError) as exc:
            _log.debug("could not reach %s for capabilities: %s", node_id.split("-")[0], exc)
            return node_id, None

    results = await asyncio.gather(*(ask(p.node_id) for p in peers))
    return {node_id: caps for node_id, caps in results if caps is not None}


async def build(
    snapshot: dict[str, Any],
    node_id: str,
    node_name: str,
    peer_capabilities: dict[str, dict[str, Any]] | None = None,
) -> list[NodeCandidate]:
    """Assemble the candidate list: this node plus every paired peer.

    ``peer_capabilities`` maps node_id -> what that peer reported when last
    asked. Absent entries fall back to the assumptions above, which is honest:
    a peer we have never measured is a guess, and the scheduler should treat it
    as one rather than as a fact.
    """
    cpu = snapshot.get("cpu") or {}
    ram = snapshot.get("ram") or {}
    gpu = snapshot.get("gpu") or None

    candidates = [
        NodeCandidate(
            node_id=node_id,
            name=node_name,
            cores=int(cpu.get("cores") or 1),
            ram_total=int(ram.get("total") or 0),
            ram_available=int(ram.get("available") or 0),
            cpu_percent=float(cpu.get("percent") or 0.0),
            # This node is the yardstick; peers are expressed relative to it.
            speed_factor=1.0,
            runtimes=runtimes.available_names(),
            encoders=list((gpu or {}).get("encoders") or []),
            has_gpu=gpu is not None,
            gpu_name=str((gpu or {}).get("name") or ""),
            latency_ms=0.0,
            throughput_mbps=0.0,
            is_self=True,
            simulated=bool(snapshot.get("simulated")),
            online=True,
        )
    ]

    for peer in await peer_db.all_peers():
        reported = (peer_capabilities or {}).get(peer.node_id) or {}
        caps = reported.get("caps") or {}
        candidates.append(
            NodeCandidate(
                node_id=peer.node_id,
                name=peer.display_name,
                cores=int(caps.get("max_cores") or 1),
                ram_total=int(caps.get("max_ram_bytes") or 0),
                ram_available=int(caps.get("max_ram_bytes") or 0),
                cpu_percent=float(reported.get("cpu_percent") or 0.0),
                speed_factor=float(reported.get("speed_factor") or ASSUMED_PEER_SPEED),
                runtimes=list(reported.get("runtimes") or []),
                encoders=list(reported.get("encoders") or []),
                has_gpu=bool(reported.get("has_gpu")),
                gpu_name=str(reported.get("gpu_name") or ""),
                latency_ms=float(reported.get("latency_ms") or ASSUMED_PEER_LATENCY_MS),
                throughput_mbps=float(
                    reported.get("throughput_mbps") or ASSUMED_PEER_THROUGHPUT_MBPS
                ),
                is_self=False,
                simulated=False,
                # A peer with no recorded address has never connected, so there
                # is nowhere to send work even though we trust it.
                online=bool(peer.last_host and peer.last_port),
            )
        )

    return candidates
