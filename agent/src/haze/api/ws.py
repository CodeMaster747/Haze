"""Live telemetry over the loopback WebSocket.

One sampler task, N subscribers.  Sampling is decoupled from delivery so that a
slow or stalled browser tab cannot slow down the sampler (or, worse, apply
backpressure that makes the agent's own resource reporting lag reality).  Each
subscriber gets a bounded queue and a slow one drops frames rather than growing
without limit -- for telemetry, the newest sample is the only one that matters.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from haze import log
from haze.config import Config

_log = log.get("api.ws")

SAMPLE_INTERVAL_S = 1.0
_QUEUE_DEPTH = 4          # ~4s of buffer; beyond that the tab is not watching


class TelemetryHub:
    """Samples this node once per second and fans the result out to sockets."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._latest: dict[str, Any] = {}
        self._started_at = time.time()

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._latest = _sample(self._cfg, self._started_at)
        self._task = asyncio.create_task(self._run(), name="haze-telemetry")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def latest(self) -> dict[str, Any]:
        return self._latest

    # --- sampling ----------------------------------------------------------

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(SAMPLE_INTERVAL_S)
            try:
                # psutil's per-core call does blocking I/O on some platforms;
                # keep it off the event loop so telemetry can never stall the
                # API or a job's progress stream.
                self._latest = await asyncio.to_thread(_sample, self._cfg, self._started_at)
            except Exception:
                _log.exception("telemetry sample failed; continuing")
                continue

            for queue in list(self._subscribers):
                # Drop for this subscriber only.  Newest-wins is correct for
                # telemetry: a backlog of stale CPU readings helps nobody, and
                # blocking here would let one stalled tab slow the sampler for
                # everyone.
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(self._latest)

    # --- delivery ----------------------------------------------------------

    async def serve(self, socket: WebSocket) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_DEPTH)
        self._subscribers.add(queue)
        try:
            # Send the current state immediately so the UI paints on connect
            # rather than showing an empty dashboard for up to a second.
            await socket.send_json({"type": "snapshot", "data": self._latest})
            while True:
                sample = await queue.get()
                await socket.send_json({"type": "telemetry", "data": sample})
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            pass
        finally:
            self._subscribers.discard(queue)


def _sample(cfg: Config, started_at: float) -> dict[str, Any]:
    """One point-in-time reading of this machine.

    M2 replaces this with the full ResourceProbe interface (host vs synthetic,
    plus GPU).  Kept real rather than stubbed even at M0 so the WebSocket path
    is exercised by genuine changing data during the browser spike.
    """
    import psutil

    vm = psutil.virtual_memory()
    per_core: list[float] = psutil.cpu_percent(interval=None, percpu=True)
    disk = psutil.disk_usage("/")

    return {
        "node_name": cfg.node_name,
        "ts": time.time(),
        "uptime_s": round(time.time() - started_at, 1),
        "cpu": {
            "percent": round(sum(per_core) / len(per_core), 1) if per_core else 0.0,
            "per_core": [round(c, 1) for c in per_core],
            "cores": psutil.cpu_count(logical=True) or 0,
            "physical_cores": psutil.cpu_count(logical=False) or 0,
        },
        "ram": {
            "total": vm.total,
            "used": vm.total - vm.available,
            "available": vm.available,
            "percent": vm.percent,
        },
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent},
        # M2 fills these in.  Present as nulls now so the TypeScript type is
        # stable from the first commit and the UI never has to feature-detect.
        "gpu": None,
        "net": None,
    }


__all__ = ["SAMPLE_INTERVAL_S", "TelemetryHub"]
