"""Merges every discovery source into one view of the network.

Runs mDNS and UDP broadcast together rather than falling back from one to the
other. They fail in different, uncorrelated ways -- multicast gets filtered,
broadcast does not cross subnets -- so running both finds strictly more, and
the union tells you *why* something is wrong: a node seen by broadcast but
never by mDNS is the signature of multicast being dropped.

Manual entries always exist as a third path, never hidden behind a "discovery
failed" state. On a guest SSID with client isolation, no amount of discovery
helps and the user needs a way in that does not depend on it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from haze import log
from haze.discovery.broadcast import BroadcastDiscovery
from haze.discovery.mdns import MdnsDiscovery
from haze.discovery.types import DiscoveredNode, Source

_log = log.get("discovery")

REACHABILITY_INTERVAL_S = 20.0
REACHABILITY_TIMEOUT_S = 2.5
SWEEP_INTERVAL_S = 5.0


class DiscoveryRegistry:
    """Everything this node currently believes is out there."""

    def __init__(self, node_id: str, name: str, node_port: int, beacon_port: int) -> None:
        self._own_id = node_id
        self._nodes: dict[str, DiscoveredNode] = {}
        self._listeners: list[asyncio.Queue[dict[str, Any]]] = []
        self._paired_ids: set[str] = set()

        self._mdns = MdnsDiscovery(node_id, name, node_port, self._record)
        self._broadcast = BroadcastDiscovery(node_id, name, node_port, beacon_port, self._record)
        self._tasks: list[asyncio.Task[None]] = []
        self._mdns_up = False
        self._broadcast_up = False

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        # Started concurrently: mDNS registration waits on network round trips,
        # and there is no reason for the broadcast beacon to queue behind it.
        self._mdns_up, self._broadcast_up = await asyncio.gather(
            self._mdns.start(), self._broadcast.start()
        )
        if not self._mdns_up and not self._broadcast_up:
            _log.warning(
                "no automatic discovery is available on this machine. Peers can still be "
                "added by address."
            )
        self._tasks = [
            asyncio.create_task(self._sweep_loop(), name="haze-discovery-sweep"),
            asyncio.create_task(self._reachability_loop(), name="haze-discovery-reach"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        await asyncio.gather(self._mdns.stop(), self._broadcast.stop(), return_exceptions=True)

    # --- recording ---------------------------------------------------------

    def _record(self, seen: DiscoveredNode) -> None:
        if seen.node_id == self._own_id:
            return

        existing = self._nodes.get(seen.node_id)
        if existing is None:
            seen.paired = seen.node_id in self._paired_ids
            self._nodes[seen.node_id] = seen
            _log.info(
                "discovered %s (%s) at %s:%d via %s",
                seen.name, seen.short_id, seen.host, seen.port, ",".join(seen.sources),
            )
            self._notify()
            return

        existing.last_seen = time.monotonic()
        existing.sources |= seen.sources
        existing.name = seen.name or existing.name
        existing.version = seen.version or existing.version
        # A node that moved (DHCP, a different interface) keeps its identity and
        # gets a new address. Identity is the key precisely so this is a
        # non-event rather than a duplicate.
        if seen.host and seen.port and (seen.host, seen.port) != (existing.host, existing.port):
            _log.info("%s moved to %s:%d", existing.short_id, seen.host, seen.port)
            existing.host, existing.port = seen.host, seen.port
            existing.reachable = None

    def add_manual(self, host: str, port: int, node_id: str = "", name: str = "") -> None:
        """Record an address the user typed in.

        Kept separate from the discovered set until a handshake proves who is
        there: we have an address but no identity, and identity is the key.
        """
        placeholder = node_id or f"manual:{host}:{port}"
        node = self._nodes.get(placeholder)
        if node is None:
            self._nodes[placeholder] = DiscoveredNode(
                node_id=placeholder,
                name=name or host,
                host=host,
                port=port,
                sources={"manual"},
            )
        else:
            node.last_seen = time.monotonic()
            node.sources.add("manual")
        self._notify()

    def set_paired(self, node_ids: set[str]) -> None:
        self._paired_ids = node_ids
        for node in self._nodes.values():
            node.paired = node.node_id in node_ids
        self._notify()

    # --- reachability ------------------------------------------------------

    async def _reachability_loop(self) -> None:
        while True:
            await asyncio.sleep(REACHABILITY_INTERVAL_S)
            for node in list(self._nodes.values()):
                if node.port:
                    node.reachable = await _can_connect(node.host, node.port)
            self._warn_about_isolation()
            self._notify()

    def _warn_about_isolation(self) -> None:
        """Name the AP-isolation case explicitly.

        Seeing a node's advertisement but never being able to open a connection
        to it is the signature of client isolation -- default-on for guest
        SSIDs and common on ISP-supplied routers. No discovery fallback can fix
        it, so reporting a generic timeout would send the user hunting in
        entirely the wrong place.
        """
        blocked = [n for n in self._nodes.values() if n.sources and n.port and n.reachable is False]
        if not blocked:
            return
        _log.warning(
            "%s advertised but unreachable (%s). If this persists, your access point is "
            "probably isolating clients from each other -- common on guest networks. "
            "Discovery cannot work around it; the machines need to be on a network that "
            "permits device-to-device traffic.",
            "node is" if len(blocked) == 1 else "nodes are",
            ", ".join(n.short_id for n in blocked),
        )

    # --- state -------------------------------------------------------------

    def _sweep(self) -> None:
        gone = [nid for nid, node in self._nodes.items() if node.stale and "manual" not in node.sources]
        for nid in gone:
            _log.info("lost %s", self._nodes[nid].short_id)
            del self._nodes[nid]
        if gone:
            self._notify()

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_S)
            self._sweep()

    def state(self) -> dict[str, Any]:
        self._sweep()
        return {
            "mdns": self._mdns_up,
            "broadcast": self._broadcast_up,
            "nodes": [n.as_dict() for n in sorted(self._nodes.values(), key=lambda n: n.name)],
        }

    def nodes(self) -> list[DiscoveredNode]:
        return list(self._nodes.values())

    # --- dashboard notification -------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self._listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def _notify(self) -> None:
        payload: dict[str, Any] = {"type": "discovery", "data": self.state()}
        for queue in list(self._listeners):
            # A dashboard this far behind re-reads full state on reconnect.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)


async def _can_connect(host: str, port: int) -> bool:
    """Plain TCP connect. Deliberately not a full handshake: this answers "is
    the port reachable", which is what distinguishes a firewall or an isolating
    access point from an authentication problem."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), REACHABILITY_TIMEOUT_S
        )
    except (TimeoutError, OSError):
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


__all__ = ["DiscoveredNode", "DiscoveryRegistry", "Source"]
