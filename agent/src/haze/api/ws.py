"""Live state over the loopback WebSocket.

Three streams share one socket: telemetry, pairing and discovery. They are
multiplexed rather than given a socket each because the pairing dialog has to
appear the instant a peer knocks, and three connections would triple the auth
surface for two very low-rate event streams.

Sampling is decoupled from delivery. A slow or stalled browser tab must not be
able to apply backpressure to the sampler -- that would make a node's own
resource reporting lag reality, which is the one thing telemetry cannot do.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from haze import log
from haze.probe.base import ResourceProbe

if TYPE_CHECKING:
    from haze.runtime import Agent

_log = log.get("api.ws")

SAMPLE_INTERVAL_S = 1.0
_QUEUE_DEPTH = 4          # ~4s of buffer; past that the tab is not watching


class TelemetryHub:
    """Samples this node once per second and fans the result out to sockets."""

    def __init__(self, probe: ResourceProbe) -> None:
        self._probe = probe
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._latest: dict[str, Any] = {}

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._latest = self._snapshot()
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

    @property
    def simulated(self) -> bool:
        return self._probe.simulated

    def _snapshot(self) -> dict[str, Any]:
        data = self._probe.sample().to_dict()
        # Travels with every sample so no consumer can render a node without
        # knowing whether its hardware is real.
        data["simulated"] = self._probe.simulated
        return data

    # --- sampling ----------------------------------------------------------

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(SAMPLE_INTERVAL_S)
            try:
                # psutil does blocking I/O on some platforms and the GPU reader
                # shells out to ioreg; keep both off the event loop so telemetry
                # can never stall the API or a job's progress stream.
                self._latest = await asyncio.to_thread(self._snapshot)
            except Exception:
                _log.exception("telemetry sample failed; continuing")
                continue

            for queue in list(self._subscribers):
                # Newest-wins: a backlog of stale CPU readings helps nobody, and
                # blocking here would let one stalled tab slow every other.
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(self._latest)

    # --- delivery ----------------------------------------------------------

    async def serve(self, socket: WebSocket, agent: Agent | None = None) -> None:
        telemetry: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_DEPTH)
        self._subscribers.add(telemetry)

        pairing_q = agent.pairing.subscribe() if agent else None
        discovery_q = agent.discovery.subscribe() if agent and agent.discovery else None

        try:
            # Paint immediately on connect rather than showing an empty
            # dashboard for up to a second.
            await socket.send_json({"type": "snapshot", "data": self._latest})
            if agent is not None:
                await socket.send_json({"type": "pairing", "data": agent.pairing.state()})
                if agent.discovery is not None:
                    await socket.send_json({"type": "discovery", "data": agent.discovery.state()})

            queues = [q for q in (telemetry, pairing_q, discovery_q) if q is not None]
            pending = {asyncio.create_task(q.get()): q for q in queues}
            try:
                while True:
                    done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        queue = pending.pop(task)
                        item = task.result()
                        # Telemetry samples are bare payloads; pairing and
                        # discovery events arrive already tagged with a type.
                        await socket.send_json(
                            item if "type" in item else {"type": "telemetry", "data": item}
                        )
                        pending[asyncio.create_task(queue.get())] = queue
            finally:
                for task in pending:
                    task.cancel()
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            pass
        finally:
            self._subscribers.discard(telemetry)
            if agent is not None:
                if pairing_q is not None:
                    agent.pairing.unsubscribe(pairing_q)
                if discovery_q is not None and agent.discovery is not None:
                    agent.discovery.unsubscribe(discovery_q)


__all__ = ["SAMPLE_INTERVAL_S", "TelemetryHub"]
