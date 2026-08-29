"""A fabricated machine, driven by a seeded random walk.

Exists so `haze devnet` can show a four-node heterogeneous cluster on one
laptop -- which matters because almost nobody evaluating this project will
install agents on four computers, and because the scheduler is uninteresting
until there is something to choose between.

Two design points make it defensible rather than decorative:

* **Seeded.** The same profile and seed produce the same trace every run, in
  development and in CI. That is what lets the browser simulation be checked
  against the Python implementation later.
* **Mean-reverting.** A plain random walk drifts to 0% or 100% and stays there;
  independent samples jitter implausibly. An Ornstein-Uhlenbeck step gives load
  that wanders and recovers the way a real machine's does.

The output is indistinguishable in *shape* from :class:`HostProbe`'s, and
deliberately distinguishable in *labelling*: ``simulated`` is True and travels
all the way to the UI badge.
"""

from __future__ import annotations

import random
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from haze.probe.base import CpuStats, DiskStats, GpuStats, MemStats, ResourceProbe, Snapshot

PROFILE_DIR = Path(__file__).resolve().parent.parent / "devnet" / "profiles"


@dataclass(frozen=True)
class GpuProfile:
    vendor: str
    name: str
    utilisation_mean: float
    vram_total: int
    vram_used: int
    encoders: list[str]


@dataclass(frozen=True)
class Profile:
    name: str
    cores: int
    physical_cores: int
    ram_bytes: int
    disk_bytes: int
    cpu_mean: float
    speed_factor: float
    gpu: GpuProfile | None = None


def available() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.toml"))


def load(name: str) -> Profile:
    path = PROFILE_DIR / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(
            f"no profile named {name!r}. Available: {', '.join(available())}"
        )
    data = tomllib.loads(path.read_text())
    gpu_data = data.get("gpu")
    return Profile(
        name=str(data["name"]),
        cores=int(data["cores"]),
        physical_cores=int(data["physical_cores"]),
        ram_bytes=int(data["ram_bytes"]),
        disk_bytes=int(data["disk_bytes"]),
        cpu_mean=float(data["cpu_mean"]),
        speed_factor=float(data["speed_factor"]),
        gpu=(
            GpuProfile(
                vendor=str(gpu_data["vendor"]),
                name=str(gpu_data["name"]),
                utilisation_mean=float(gpu_data["utilisation_mean"]),
                vram_total=int(gpu_data["vram_total"]),
                vram_used=int(gpu_data["vram_used"]),
                encoders=list(gpu_data.get("encoders", [])),
            )
            if gpu_data
            else None
        ),
    )


def _ou_step(current: float, mean: float, reversion: float, volatility: float,
             rng: random.Random) -> float:
    """One Ornstein-Uhlenbeck step, clamped to a percentage."""
    shock = (rng.random() - 0.5) * 2 * volatility
    return min(100.0, max(0.0, current + reversion * (mean - current) + shock))


class SyntheticProbe(ResourceProbe):
    """A node's worth of plausible, reproducible telemetry."""

    def __init__(self, profile: Profile, seed: int = 0x48415A45) -> None:  # "HAZE"
        self._profile = profile
        self._rng = random.Random(seed)  # noqa: S311 -- telemetry, not cryptography
        self._started_at = time.time()
        self._cpu = profile.cpu_mean
        self._ram_percent = 30.0 + self._rng.random() * 25.0
        self._disk_percent = 20.0 + self._rng.random() * 40.0
        self._gpu_util = profile.gpu.utilisation_mean if profile.gpu else 0.0

    @property
    def simulated(self) -> bool:
        return True

    @property
    def profile(self) -> Profile:
        return self._profile

    def sample(self) -> Snapshot:
        p = self._profile
        self._cpu = _ou_step(self._cpu, p.cpu_mean, 0.18, 9.0, self._rng)
        self._ram_percent = _ou_step(self._ram_percent, 45.0, 0.06, 2.5, self._rng)
        if p.gpu:
            self._gpu_util = _ou_step(self._gpu_util, p.gpu.utilisation_mean, 0.12, 11.0, self._rng)

        ram_used = round(self._ram_percent / 100 * p.ram_bytes)
        disk_used = round(self._disk_percent / 100 * p.disk_bytes)

        return Snapshot(
            node_name=p.name,
            ts=time.time(),
            uptime_s=round(time.time() - self._started_at, 1),
            cpu=CpuStats(
                percent=round(self._cpu, 1),
                # Spread the cores deterministically around the aggregate so the
                # core grid looks like a machine rather than N identical bars.
                per_core=[
                    round(min(100.0, max(0.0, self._cpu + ((i * 37) % 23) - 11)), 1)
                    for i in range(p.cores)
                ],
                cores=p.cores,
                physical_cores=p.physical_cores,
            ),
            ram=MemStats(
                total=p.ram_bytes,
                used=ram_used,
                available=p.ram_bytes - ram_used,
                percent=round(self._ram_percent, 1),
            ),
            disk=DiskStats(
                total=p.disk_bytes,
                used=disk_used,
                free=p.disk_bytes - disk_used,
                percent=round(self._disk_percent, 1),
            ),
            gpu=(
                GpuStats(
                    vendor=p.gpu.vendor,
                    name=p.gpu.name,
                    utilisation=round(self._gpu_util, 1),
                    # 0 in the profile means "this platform has no such number"
                    # -- unified memory. Mirrors what the real Apple probe does.
                    vram_total=p.gpu.vram_total or None,
                    vram_used=p.gpu.vram_used or None,
                    encoders=p.gpu.encoders,
                )
                if p.gpu
                else None
            ),
            net=None,
        )
