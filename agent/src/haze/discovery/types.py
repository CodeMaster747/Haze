"""What discovery produces."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["mdns", "broadcast", "manual", "paired"]

# A node that has not been heard from in this long is treated as gone. Three
# missed beacons rather than one, so a single dropped multicast packet -- which
# is routine on WiFi -- does not make a machine flicker out of the list.
STALE_AFTER_S = 18.0


@dataclass
class DiscoveredNode:
    """A Haze node seen on the network. Not necessarily paired, or reachable."""

    node_id: str
    """The identity, and the only safe key.

    Never key discovery on address: `haze devnet` runs four agents on one host,
    so they all advertise the same IP, and a machine's address changes across
    reconnects while its identity does not.
    """

    name: str
    host: str
    port: int
    sources: set[Source] = field(default_factory=set)
    """Which mechanisms have seen it. Shown in the UI because "found by
    broadcast but not mDNS" is the signature of multicast being filtered, and
    naming that saves a user an hour."""

    platform: str = ""
    version: str = ""
    first_seen: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    paired: bool = False
    reachable: bool | None = None
    """None until probed. False with sources non-empty is the AP-isolation
    signature: we can see its advertisement but cannot open a connection."""

    @property
    def stale(self) -> bool:
        return (time.monotonic() - self.last_seen) > STALE_AFTER_S

    @property
    def short_id(self) -> str:
        return self.node_id.split("-")[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "short_id": self.short_id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "sources": sorted(self.sources),
            "platform": self.platform,
            "version": self.version,
            "paired": self.paired,
            "reachable": self.reachable,
            "age_s": round(time.monotonic() - self.last_seen, 1),
        }
