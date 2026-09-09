"""Building the scheduler's input from what this agent actually knows.

Kept separate from `decide` on purpose: this half touches the database, the
telemetry hub and the peer table, and the moment any of that leaks into the
scoring the function stops being pure -- and the TypeScript mirror stops being
checkable against it.
"""

from __future__ import annotations

import asyncio
import time
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

CAPABILITIES_TTL_S = 30.0
"""How long a peer's *answer* stays good.

What a peer can run changes when someone installs software on it, not from one
second to the next, so re-asking on every submission would spend a network
round trip to re-learn a fact that has not moved.
"""

CAPABILITIES_MISS_TTL_S = 5.0
"""How long a peer's *silence* stays good -- much shorter, on purpose.

The asymmetry is the whole design. A stale success is harmless; a stale failure
is not, because a peer that did not answer reports no runtimes, and
`_ineligibility` turns that into "does not have hashbench". Caching silence for
thirty seconds would lock a machine that just woke up out of every placement
for half a minute.
"""

SUBMIT_PROBE_TIMEOUT_S = 1.5
"""Per-peer timeout on the submission path.

`probe_peers` already asks every peer concurrently, so this is not a sum -- but
it is the delay one sleeping peer adds to a job the user is waiting on. The
preview path keeps the more patient default: it is asked rarely and deliberately.
"""


async def probe_peers(
    identity: Any, cfg: Any, timeout_s: float = 4.0, only: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Ask every paired peer what it can run, concurrently.

    Failures are not errors: a peer that is asleep or unreachable simply has no
    entry, and :func:`build` falls back to the pessimistic assumptions above.
    Placement should degrade to a guess rather than fail outright.

    ``only`` restricts the question to those node ids, which is how
    :func:`cached_capabilities` re-asks just the peers whose answers expired.
    """
    from haze.transport import client as node_client

    peers = await peer_db.all_peers()
    if only is not None:
        wanted = set(only)
        peers = [p for p in peers if p.node_id in wanted]
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


class _Cached:
    """One peer's last answer, and when it stops being trustworthy."""

    __slots__ = ("caps", "expires_at")

    def __init__(self, caps: dict[str, Any] | None, expires_at: float) -> None:
        self.caps = caps
        self.expires_at = expires_at


_EXPIRED = _Cached(None, 0.0)
"""Stands in for a peer we have never asked, so the staleness check has no
special case for "absent" separate from "out of date"."""

_cache: dict[str, _Cached] = {}
_cache_lock = asyncio.Lock()


def invalidate_capabilities() -> None:
    """Forget every cached answer.

    Deliberately *not* wired into pairing and unpairing, because the cache
    needs no help there: it is keyed per peer and reconciled against the live
    peer list on every call, so a newly paired node is simply absent and gets
    asked immediately, and an unpaired one is dropped. Pairing a machine and
    then being told for thirty seconds that it cannot run anything would be the
    kind of small lie that makes a scheduler feel broken -- this is the
    structure that prevents it, rather than a callback that has to remember to
    fire.

    It exists for the case that is genuinely a reset: tests, and any future
    "re-probe now" the dashboard grows.
    """
    _cache.clear()


async def cached_capabilities(
    identity: Any, cfg: Any, timeout_s: float = SUBMIT_PROBE_TIMEOUT_S
) -> dict[str, dict[str, Any]]:
    """:func:`probe_peers`, but only for the peers whose answers have expired.

    This is what the submission path uses. Placing a job must not cost a full
    round of TLS handshakes every time, and the things being cached change on
    the timescale of installing software.
    """
    peers = await peer_db.all_peers()

    async with _cache_lock:
        # Inside the lock: two submissions landing together should produce one
        # round of probes, not two.
        now = time.monotonic()
        # Reconcile against the live peer list first, so unpairing a node
        # forgets it rather than leaving it to expire -- and so unpairing the
        # *last* one is not a special case that skips the cleanup.
        live = {p.node_id for p in peers}
        for node_id in list(_cache):
            if node_id not in live:
                del _cache[node_id]

        stale = [p.node_id for p in peers if _cache.get(p.node_id, _EXPIRED).expires_at <= now]
        if stale:
            fresh = await probe_peers(identity, cfg, timeout_s, only=stale)
            for node_id in stale:
                caps = fresh.get(node_id)
                _cache[node_id] = _Cached(
                    caps,
                    now + (CAPABILITIES_TTL_S if caps is not None else CAPABILITIES_MISS_TTL_S),
                )

        return {
            node_id: entry.caps
            for node_id, entry in _cache.items()
            if entry.caps is not None
        }


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

    # One query for every peer's pinned addresses rather than one per peer:
    # this loop already has the whole peer list in hand.
    pins = await peer_db.all_pins()

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
                # A peer with no address at all has never connected and has
                # none pinned, so there is nowhere to send work even though we
                # trust it. A pinned address counts: a peer reachable only over
                # an overlay network would otherwise be scored offline here
                # while `haze ping` reported it up.
                online=bool(pins.get(peer.node_id) or (peer.last_host and peer.last_port)),
            )
        )

    return candidates
