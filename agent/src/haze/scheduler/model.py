"""Inputs and outputs of a placement decision.

Everything here is plain data. The scheduler is a pure function over these
types -- no clock, no randomness, no I/O -- which is what makes it possible to
mirror in TypeScript and check both against the same golden corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NodeCandidate:
    """One node the scheduler may place work on."""

    node_id: str
    name: str
    cores: int
    ram_total: int
    ram_available: int
    cpu_percent: float
    """Current load, 0-100. Higher means less headroom."""
    speed_factor: float
    """Relative compute throughput; 1.0 is a baseline laptop."""
    runtimes: list[str] = field(default_factory=list)
    encoders: list[str] = field(default_factory=list)
    has_gpu: bool = False
    gpu_name: str = ""
    latency_ms: float = 0.0
    throughput_mbps: float = 1000.0
    is_self: bool = False
    simulated: bool = False
    online: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeCandidate:
        return cls(
            node_id=str(data["node_id"]),
            name=str(data.get("name") or ""),
            cores=int(data.get("cores") or 0),
            ram_total=int(data.get("ram_total") or 0),
            ram_available=int(data.get("ram_available") or 0),
            cpu_percent=float(data.get("cpu_percent") or 0.0),
            speed_factor=float(data.get("speed_factor") or 1.0),
            runtimes=list(data.get("runtimes") or []),
            encoders=list(data.get("encoders") or []),
            has_gpu=bool(data.get("has_gpu")),
            gpu_name=str(data.get("gpu_name") or ""),
            latency_ms=float(data.get("latency_ms") or 0.0),
            throughput_mbps=float(data.get("throughput_mbps") or 1000.0),
            is_self=bool(data.get("is_self")),
            simulated=bool(data.get("simulated")),
            online=bool(data.get("online", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "name": self.name, "cores": self.cores,
            "ram_total": self.ram_total, "ram_available": self.ram_available,
            "cpu_percent": self.cpu_percent, "speed_factor": self.speed_factor,
            "runtimes": self.runtimes, "encoders": self.encoders,
            "has_gpu": self.has_gpu, "gpu_name": self.gpu_name,
            "latency_ms": self.latency_ms, "throughput_mbps": self.throughput_mbps,
            "is_self": self.is_self, "simulated": self.simulated, "online": self.online,
        }


@dataclass(frozen=True)
class JobRequirement:
    """What a job needs, for placement purposes."""

    runtime: str
    cpu_cores: int = 1
    ram_bytes: int = 1 << 30
    needs_gpu: bool = False
    preferred_encoders: list[str] = field(default_factory=list)
    input_bytes: int = 0
    """Bytes that must reach the chosen node. The reason a faster machine can
    still be the wrong choice."""
    work_units: float = 1.0
    """Rough compute size, in units where 1.0 takes one second on a node with
    speed_factor 1.0. Only ratios matter."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRequirement:
        return cls(
            runtime=str(data["runtime"]),
            cpu_cores=int(data.get("cpu_cores") or 1),
            ram_bytes=int(data.get("ram_bytes") or 1 << 30),
            needs_gpu=bool(data.get("needs_gpu")),
            preferred_encoders=list(data.get("preferred_encoders") or []),
            input_bytes=int(data.get("input_bytes") or 0),
            work_units=float(data.get("work_units") or 1.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime, "cpu_cores": self.cpu_cores,
            "ram_bytes": self.ram_bytes, "needs_gpu": self.needs_gpu,
            "preferred_encoders": self.preferred_encoders,
            "input_bytes": self.input_bytes, "work_units": self.work_units,
        }


@dataclass(frozen=True)
class Assessment:
    """How one candidate scored, and why."""

    node_id: str
    name: str
    eligible: bool
    score: float
    """0-1. Meaningless when ``eligible`` is False."""
    dimensions: dict[str, float]
    reasons: list[str]
    """Human-readable, ordered most-important first. This is what
    `haze explain` prints and what the dashboard shows."""
    estimated_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "name": self.name, "eligible": self.eligible,
            "score": self.score, "dimensions": self.dimensions,
            "reasons": self.reasons, "estimated_seconds": self.estimated_seconds,
        }


@dataclass(frozen=True)
class Decision:
    """The outcome. Always includes every candidate, winners and losers alike."""

    chosen: str | None
    assessments: list[Assessment]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen": self.chosen,
            "summary": self.summary,
            "assessments": [a.to_dict() for a in self.assessments],
        }
