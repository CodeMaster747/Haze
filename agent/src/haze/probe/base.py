"""What a node knows about its own hardware.

One interface, two implementations. :class:`HostProbe` reads the real machine;
:class:`SyntheticProbe` fabricates a plausible one from a profile so that
`haze devnet` can show a four-node cluster on a single laptop.

The split is not a testing convenience -- it is a correctness requirement. A
node built from a profile carries ``simulated=True`` all the way to the UI, and
every surface that renders a node shows that. An unbadged synthetic "RTX 4090"
on a machine with no NVIDIA GPU is the fastest way to turn this project's best
demo asset into its worst credibility problem.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CpuStats:
    percent: float
    per_core: list[float]
    cores: int
    physical_cores: int


@dataclass(frozen=True)
class MemStats:
    total: int
    used: int
    available: int
    percent: float


@dataclass(frozen=True)
class DiskStats:
    total: int
    used: int
    free: int
    percent: float


@dataclass(frozen=True)
class GpuStats:
    vendor: str
    """One of nvidia | apple | amd | intel."""
    name: str
    utilisation: float | None
    vram_total: int | None
    """``None`` where the platform genuinely has no such number to report.

    Apple Silicon uses unified memory: there is no separate VRAM pool, and the
    sudoless ``ioreg`` path exposes in-use bytes but no device total. Reporting
    ``None`` and rendering a dash is honest; inventing a total would not be.
    """
    vram_used: int | None
    encoders: list[str] = field(default_factory=list)
    """Hardware video encoders ffmpeg can actually use here, e.g.
    ``h264_videotoolbox``. A real scheduler input: "send the HEVC encode to the
    node with NVENC" is a placement decision this makes possible."""


@dataclass(frozen=True)
class Snapshot:
    """One point-in-time reading of a node."""

    node_name: str
    ts: float
    uptime_s: float
    cpu: CpuStats
    ram: MemStats
    disk: DiskStats
    gpu: GpuStats | None
    net: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceProbe(Protocol):
    """Samples a node once per call."""

    @property
    def simulated(self) -> bool:
        """True when this node's hardware is fabricated from a profile."""
        ...

    def sample(self) -> Snapshot: ...
