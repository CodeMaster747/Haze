"""The real machine, via psutil."""

from __future__ import annotations

import time

import psutil

from haze.probe import encoders, gpu
from haze.probe.base import CpuStats, DiskStats, GpuStats, MemStats, ResourceProbe, Snapshot


class HostProbe(ResourceProbe):
    """Reads this machine's actual CPU, memory, disk and GPU."""

    def __init__(self, node_name: str) -> None:
        self._node_name = node_name
        self._started_at = time.time()
        self._encoders = encoders.detect()
        self._gpu = gpu.detect(self._encoders)
        # psutil's first percpu call returns times since boot, which reads as a
        # meaningless spike. Prime it so the first real sample is a delta.
        psutil.cpu_percent(interval=None, percpu=True)

    @property
    def simulated(self) -> bool:
        return False

    def sample(self) -> Snapshot:
        vm = psutil.virtual_memory()
        per_core: list[float] = psutil.cpu_percent(interval=None, percpu=True)
        disk = psutil.disk_usage("/")

        gpu_stats: GpuStats | None = self._gpu.read() if self._gpu else None

        return Snapshot(
            node_name=self._node_name,
            ts=time.time(),
            uptime_s=round(time.time() - self._started_at, 1),
            cpu=CpuStats(
                percent=round(sum(per_core) / len(per_core), 1) if per_core else 0.0,
                per_core=[round(c, 1) for c in per_core],
                cores=psutil.cpu_count(logical=True) or 0,
                physical_cores=psutil.cpu_count(logical=False) or 0,
            ),
            ram=MemStats(
                total=vm.total,
                used=vm.total - vm.available,
                available=vm.available,
                percent=vm.percent,
            ),
            disk=DiskStats(
                total=disk.total, used=disk.used, free=disk.free, percent=disk.percent
            ),
            gpu=gpu_stats,
            net=None,
        )
