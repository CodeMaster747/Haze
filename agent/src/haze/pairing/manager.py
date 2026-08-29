"""Pairing state: what is armed, what is pending, who has confirmed.

Both ends must confirm independently. That is the entire security property —
if only the initiator confirmed, an attacker who reached the listener could
pair itself while the owner was away from the machine.

Pairing is armed explicitly and briefly. A node that is always willing to pair
is a node any device on the LAN can attempt to join, and while the SAS would
still protect against that succeeding, an unarmed listener means the attempt
never starts.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Literal

from haze import log
from haze.pairing import sas
from haze.transport.handshake import PeerIdentity

_log = log.get("pairing")

ARM_TTL_S = 180.0
"""How long pairing stays open. Long enough to walk to the other machine."""

CONFIRM_TIMEOUT_S = 120.0
"""How long a pending request waits for its user. Shorter than ARM_TTL_S so a
stalled request cannot outlive the window it was created in."""

Decision = Literal["pending", "confirmed", "rejected", "expired"]
Direction = Literal["incoming", "outgoing"]


@dataclass
class PendingPairing:
    """One in-flight pairing request, from this node's point of view."""

    session_id: str
    peer: PeerIdentity
    direction: Direction
    """Who dialled. Both ends confirm identically; this only changes the wording
    the UI uses so the user knows which machine they are looking at."""
    sas_digits: str
    sas_words: list[str]
    created_at: float
    """time.monotonic(). Never wall clock -- an NTP step must not be able to
    extend or shorten the window."""

    decision: Decision = "pending"
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def expired(self) -> bool:
        return self.age_s > CONFIRM_TIMEOUT_S

    def as_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "direction": self.direction,
            "node_id": self.peer.node_id,
            "short_id": self.peer.node_id.split("-")[0],
            "name": self.peer.display_name,
            "platform": self.peer.platform,
            "version": self.peer.agent_version,
            "sas_digits": self.sas_digits,
            "sas_words": self.sas_words,
            "decision": self.decision,
            "expires_in_s": max(0.0, round(CONFIRM_TIMEOUT_S - self.age_s, 1)),
        }


class PairingManager:
    """Per-agent pairing state. One instance, owned by the running agent."""

    def __init__(self, own_public_key: bytes) -> None:
        self._own_key = own_public_key
        self._armed_until: float = 0.0
        self._pending: dict[str, PendingPairing] = {}
        self._listeners: list[asyncio.Queue[dict[str, object]]] = []
        self._last_error: str | None = None

    # --- arming ------------------------------------------------------------

    def arm(self, ttl_s: float = ARM_TTL_S) -> float:
        self._armed_until = time.monotonic() + ttl_s
        _log.info("pairing armed for %.0fs", ttl_s)
        self._notify()
        return ttl_s

    def disarm(self) -> None:
        self._armed_until = 0.0
        # Anything still waiting is abandoned: the user closed the window.
        for pending in list(self._pending.values()):
            if pending.decision == "pending":
                self._settle(pending, "rejected")
        _log.info("pairing disarmed")
        self._notify()

    @property
    def is_armed(self) -> bool:
        return time.monotonic() < self._armed_until

    @property
    def arm_remaining_s(self) -> float:
        return max(0.0, self._armed_until - time.monotonic())

    # --- pending requests --------------------------------------------------

    def open_request(self, peer: PeerIdentity, direction: Direction = "incoming") -> PendingPairing:
        """Record a pairing request and compute the SAS the user will compare.

        Used for both directions: the SAS is derived from the two public keys,
        so which side dialled makes no difference to what is displayed.
        """
        self._sweep()
        pending = PendingPairing(
            session_id=secrets.token_urlsafe(12),
            peer=peer,
            direction=direction,
            sas_digits=sas.digits(self._own_key, peer.public_key),
            sas_words=sas.words(self._own_key, peer.public_key),
            created_at=time.monotonic(),
        )
        self._pending[pending.session_id] = pending
        _log.info(
            "%s pairing with %s (%s) -- SAS %s",
            direction, peer.display_name, peer.node_id.split("-")[0], pending.sas_digits,
        )
        self._notify()
        return pending

    def get(self, session_id: str) -> PendingPairing | None:
        pending = self._pending.get(session_id)
        if pending and pending.expired and pending.decision == "pending":
            self._settle(pending, "expired")
        return pending

    def confirm(self, session_id: str) -> bool:
        pending = self.get(session_id)
        if pending is None or pending.decision != "pending":
            return False
        self._settle(pending, "confirmed")
        return True

    def reject(self, session_id: str) -> bool:
        pending = self.get(session_id)
        if pending is None or pending.decision != "pending":
            return False
        self._settle(pending, "rejected")
        return True

    async def wait_for_decision(self, session_id: str) -> Decision:
        """Block until this node's user decides, or the request expires."""
        pending = self._pending.get(session_id)
        if pending is None:
            return "expired"
        try:
            await asyncio.wait_for(pending._event.wait(), CONFIRM_TIMEOUT_S)
        except TimeoutError:
            self._settle(pending, "expired")
        return pending.decision

    def pending_list(self) -> list[dict[str, object]]:
        self._sweep()
        return [p.as_dict() for p in self._pending.values() if p.decision == "pending"]

    def forget(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
        self._notify()

    # --- dashboard notification -------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=8)
        self._listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def state(self) -> dict[str, object]:
        return {
            "armed": self.is_armed,
            "arm_remaining_s": round(self.arm_remaining_s, 1),
            "pending": self.pending_list(),
            "last_error": self._last_error,
        }

    def set_last_error(self, message: str) -> None:
        """Surface a failed outgoing attempt in the UI.

        Without this a dashboard-initiated pairing that cannot reach the peer
        would simply show nothing happening, which is indistinguishable from
        "still waiting for the other user".
        """
        self._last_error = message
        self._notify()

    def clear_last_error(self) -> None:
        self._last_error = None
        self._notify()

    def _notify(self) -> None:
        payload: dict[str, object] = {"type": "pairing", "data": self.state()}
        for queue in list(self._listeners):
            # A dashboard this far behind will re-read the full state when it
            # reconnects, so dropping a notification loses nothing.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    # --- internals ---------------------------------------------------------

    def _settle(self, pending: PendingPairing, decision: Decision) -> None:
        pending.decision = decision
        pending._event.set()
        _log.info("pairing %s: %s", pending.session_id, decision)
        self._notify()

    def _sweep(self) -> None:
        for pending in list(self._pending.values()):
            if pending.decision == "pending" and pending.expired:
                self._settle(pending, "expired")
            # Keep settled requests briefly so the UI can show the outcome,
            # then drop them.
            elif pending.decision != "pending" and pending.age_s > CONFIRM_TIMEOUT_S * 2:
                del self._pending[pending.session_id]
