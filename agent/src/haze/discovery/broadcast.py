"""UDP broadcast discovery -- the fallback that makes this work on real WiFi.

mDNS is the right answer on paper and fails often enough in practice that
shipping it alone would be a bug. IGMP snooping on mesh access points drops
multicast (notably after a client roams between APs, where the multicast path
stays broken until the switch is restarted), and consumer routers filter it in
ways that are hard to predict and harder to explain to a user.

Broadcast survives several configurations that kill multicast, costs about
sixty lines, and needs no daemon. It is deliberately the *second* mechanism
rather than the only one, because broadcast does not cross subnets and mDNS
sometimes does.

The payload carries the node ID, so a listener keys on identity rather than
address -- which matters immediately, since `haze devnet` runs several agents
behind one IP.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from collections.abc import Callable
from typing import Any

import haze
from haze import log
from haze.discovery.types import DiscoveredNode

_log = log.get("discovery.broadcast")

BEACON_INTERVAL_S = 5.0
MAX_DATAGRAM = 1024

OnSeen = Callable[[DiscoveredNode], None]


class _BeaconProtocol(asyncio.DatagramProtocol):
    def __init__(self, own_node_id: str, on_seen: OnSeen) -> None:
        self._own_node_id = own_node_id
        self._on_seen = on_seen
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str | Any, ...]) -> None:
        if len(data) > MAX_DATAGRAM:
            return
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return  # something else on the port; not our business
        if not isinstance(payload, dict) or payload.get("magic") != "haze":
            return

        node_id = payload.get("id")
        if not isinstance(node_id, str) or node_id == self._own_node_id:
            return  # our own beacon, reflected back

        port = payload.get("port")
        self._on_seen(
            DiscoveredNode(
                node_id=node_id,
                name=str(payload.get("name") or "unnamed"),
                host=str(addr[0]),
                port=int(port) if isinstance(port, int) and 1 <= port <= 65535 else 0,
                sources={"broadcast"},
                platform=str(payload.get("platform") or ""),
                version=str(payload.get("version") or ""),
            )
        )

    def error_received(self, exc: Exception) -> None:
        _log.debug("beacon socket error: %s", exc)


class BroadcastDiscovery:
    """Announces this node and listens for others."""

    def __init__(self, node_id: str, name: str, node_port: int, beacon_port: int,
                 on_seen: OnSeen) -> None:
        self._node_id = node_id
        self._name = name
        self._node_port = node_port
        self._beacon_port = beacon_port
        self._on_seen = on_seen
        self._transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> bool:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        with contextlib.suppress(AttributeError, OSError):
            # Lets several agents share the port on one host, which is exactly
            # what `haze devnet` does.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        try:
            sock.bind(("", self._beacon_port))
        except OSError as exc:
            sock.close()
            _log.warning(
                "could not bind UDP %d for discovery beacons (%s). Other machines will not "
                "find this node automatically -- add it by address instead.",
                self._beacon_port, exc,
            )
            return False

        transport, _ = await loop.create_datagram_endpoint(
            lambda: _BeaconProtocol(self._node_id, self._on_seen), sock=sock
        )
        self._transport = transport
        self._task = asyncio.create_task(self._announce_loop(), name="haze-beacon")
        _log.info("broadcast discovery on UDP %d", self._beacon_port)
        return True

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._transport:
            self._transport.close()
            self._transport = None

    async def _announce_loop(self) -> None:
        payload = json.dumps(
            {
                "magic": "haze",
                "v": haze.PROTOCOL_VERSION,
                "id": self._node_id,
                "name": self._name,
                "port": self._node_port,
                "version": haze.__version__,
            },
            separators=(",", ":"),
        ).encode()

        while True:
            if self._transport is not None:
                # 255.255.255.255 is link-local and not forwarded by routers, so
                # this reaches the local segment only -- which is the intent.
                with contextlib.suppress(OSError):
                    self._transport.sendto(payload, ("255.255.255.255", self._beacon_port))
            await asyncio.sleep(BEACON_INTERVAL_S)
