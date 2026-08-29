"""GPU telemetry, per platform.

There is no cross-platform library worth depending on here, so this is a small
adapter per vendor with an honest "unknown" fallback. Each is probed once at
startup; whichever responds becomes this node's reader for the process
lifetime.

What is obtainable without elevated privileges differs sharply by platform, and
the design reflects that rather than papering over it:

* **Apple Silicon** -- ``ioreg -rc AGXAccelerator`` exposes utilisation and
  in-use memory with no root. ``powermetrics`` (what asitop uses) would give
  more, but needs sudo, and a personal tool that demands a password to draw a
  graph is a tool nobody runs. Unified memory means there is no VRAM total.
* **NVIDIA** -- NVML gives everything, including a real VRAM total.
* **Everything else** -- reported as absent. A wrong number is worse than none.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Protocol

from haze import log
from haze.probe.base import GpuStats

_log = log.get("probe.gpu")

_IOREG_TIMEOUT_S = 2.0


class GpuReader(Protocol):
    def read(self) -> GpuStats | None: ...


class AppleGpuReader:
    """Apple Silicon, without root.

    Parses the ``PerformanceStatistics`` dictionary out of ``ioreg``. The
    interesting keys are ``Device Utilization %`` and ``In use system memory``.
    """

    _UTIL = re.compile(r'"Device Utilization %"=(\d+)')
    _IN_USE = re.compile(r'"In use system memory"=(\d+)')
    _MODEL = re.compile(r'"model" = "([^"]+)"')

    def __init__(self, encoders: list[str] | None = None) -> None:
        self._name = "Apple GPU"
        self._encoders: list[str] = encoders or []

    def probe(self) -> bool:
        if platform.system() != "Darwin" or not shutil.which("ioreg"):
            return False
        text = self._ioreg()
        if text is None or ("AGXAccelerator" not in text and "PerformanceStatistics" not in text):
            return False
        match = self._MODEL.search(text)
        if match:
            self._name = match.group(1)
        return self._UTIL.search(text) is not None

    def read(self) -> GpuStats | None:
        text = self._ioreg()
        if text is None:
            return None
        util = self._UTIL.search(text)
        in_use = self._IN_USE.search(text)
        return GpuStats(
            vendor="apple",
            name=self._name,
            utilisation=float(util.group(1)) if util else None,
            # Unified memory: no device-local pool, so no total to report.
            vram_total=None,
            vram_used=int(in_use.group(1)) if in_use else None,
            encoders=self._encoders,
        )

    def _ioreg(self) -> str | None:
        try:
            result = subprocess.run(
                ["/usr/sbin/ioreg", "-rc", "AGXAccelerator", "-d", "1"],
                capture_output=True,
                timeout=_IOREG_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else None


class NvidiaGpuReader:
    """NVIDIA via NVML. Requires the `nvidia` extra."""

    def __init__(self, encoders: list[str] | None = None) -> None:
        self._nvml: object | None = None
        self._handle: object | None = None
        self._name = "NVIDIA GPU"
        self._encoders: list[str] = encoders or []

    def probe(self) -> bool:
        try:
            import pynvml
        except ImportError:
            return False
        try:
            pynvml.nvmlInit()
            if pynvml.nvmlDeviceGetCount() == 0:
                return False
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            self._name = name.decode() if isinstance(name, bytes) else str(name)
        except Exception as exc:
            _log.debug("NVML unavailable: %s", exc)
            return False
        self._nvml = pynvml
        self._handle = handle
        return True

    def read(self) -> GpuStats | None:
        if self._nvml is None or self._handle is None:
            return None
        pynvml = self._nvml
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(self._handle)  # type: ignore[attr-defined]
            mem = pynvml.nvmlDeviceGetMemoryInfo(self._handle)  # type: ignore[attr-defined]
        except Exception:
            return None
        return GpuStats(
            vendor="nvidia",
            name=self._name,
            utilisation=float(util.gpu),
            vram_total=int(mem.total),
            vram_used=int(mem.used),
            encoders=self._encoders,
        )


def detect(encoders: list[str] | None = None) -> GpuReader | None:
    """Pick a reader for this machine, or ``None`` if no GPU is legible.

    Probed once. A machine does not grow a GPU while the agent runs, and
    re-probing per sample would mean shelling out to ioreg every second.
    """
    for candidate in (NvidiaGpuReader(encoders), AppleGpuReader(encoders)):
        if candidate.probe():
            stats = candidate.read()
            _log.info("gpu: %s", stats.name if stats else type(candidate).__name__)
            return candidate
    _log.info("gpu: none detected (this node reports CPU, memory and disk only)")
    return None
