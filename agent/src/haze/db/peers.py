"""Peer queries. The only module that decides who is trusted."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select

from haze import log
from haze.db.models import Peer, PinnedAddress
from haze.db.session import session

_log = log.get("db.peers")


async def all_peers() -> list[Peer]:
    async with session() as s:
        result = await s.scalars(select(Peer).order_by(Peer.display_name))
        return list(result)


async def get(node_id: str) -> Peer | None:
    async with session() as s:
        peer: Peer | None = await s.get(Peer, node_id)
        return peer


async def by_public_key(public_key: bytes) -> Peer | None:
    """Look a peer up by its raw Ed25519 key -- the identity the handshake proves."""
    async with session() as s:
        peer: Peer | None = await s.scalar(select(Peer).where(Peer.public_key == public_key))
        return peer


async def trust_bundle() -> list[bytes]:
    """DER certificates of every paired peer, for the TLS trust store."""
    async with session() as s:
        result = await s.scalars(select(Peer.cert_der))
        return list(result)


async def upsert(
    *,
    node_id: str,
    public_key: bytes,
    cert_der: bytes,
    display_name: str,
    platform: str = "",
    agent_version: str = "",
    host: str = "",
    port: int = 0,
) -> Peer:
    """Record a pairing, or refresh an existing peer's details.

    Re-pairing an existing node updates its certificate and metadata but keeps
    ``paired_at`` and ``policy_generation`` -- the user already made the trust
    decision, and silently resetting their permissions would be surprising.
    """
    async with session() as s:
        peer = await s.get(Peer, node_id)
        if peer is None:
            peer = Peer(node_id=node_id, public_key=public_key, cert_der=cert_der,
                        display_name=display_name)
            s.add(peer)
            _log.info("paired with %s (%s)", display_name, node_id.split("-")[0])
        elif peer.public_key != public_key:
            # The node ID is SHA-256 of the public key, so this means a hash
            # collision or a bug -- never a legitimate key rotation.
            raise ValueError(f"node {node_id} presented a different public key than recorded")
        else:
            peer.cert_der = cert_der
            peer.display_name = display_name

        peer.platform = platform
        peer.agent_version = agent_version
        if host:
            peer.last_host = host
            peer.last_port = port
        peer.last_seen_at = dt.datetime.now(dt.UTC)
        await s.commit()
        return peer


async def touch(node_id: str, host: str = "", port: int = 0) -> None:
    async with session() as s:
        peer = await s.get(Peer, node_id)
        if peer is None:
            return
        peer.last_seen_at = dt.datetime.now(dt.UTC)
        if host:
            peer.last_host = host
            peer.last_port = port
        await s.commit()


async def remove(node_id: str) -> bool:
    """Unpair. The peer leaves the trust set, so its next connection is refused
    at the handshake with `not_paired`."""
    async with session() as s:
        peer = await s.get(Peer, node_id)
        if peer is None:
            return False
        # Explicitly, not by FK cascade. `PRAGMA foreign_keys` is per-connection
        # and this engine pools connections, so the cascade fires only on
        # whichever connection happened to run the pragma. Beyond that, unpair
        # is the user's "forget this machine" gesture: a surviving pin would
        # reattach to the same node if it were ever re-paired, because the node
        # ID is derived from the public key and does not change.
        await s.execute(delete(PinnedAddress).where(PinnedAddress.node_id == node_id))
        await s.delete(peer)
        await s.commit()
        _log.info("unpaired %s", node_id.split("-")[0])
        return True


# --- pinned addresses -------------------------------------------------------


async def pinned(node_id: str) -> list[PinnedAddress]:
    """Addresses pinned for one peer, most recently pinned first."""
    async with session() as s:
        result = await s.scalars(
            select(PinnedAddress)
            .where(PinnedAddress.node_id == node_id)
            .order_by(PinnedAddress.set_at.desc(), PinnedAddress.host)
        )
        return list(result)


async def all_pins() -> dict[str, list[PinnedAddress]]:
    """Every pin, grouped by node.

    One query rather than one per peer: the callers that need this
    (`GET /peers`, the scheduler's candidate list) are already iterating
    :func:`all_peers`.
    """
    async with session() as s:
        result = await s.scalars(
            select(PinnedAddress).order_by(PinnedAddress.set_at.desc(), PinnedAddress.host)
        )
        grouped: dict[str, list[PinnedAddress]] = {}
        for row in result:
            grouped.setdefault(row.node_id, []).append(row)
        return grouped


async def pin_address(node_id: str, host: str, port: int) -> bool:
    """Pin ``host:port`` for a peer, replacing any address pinned before.

    Returns False if the node is not paired -- pinning an address for a machine
    we have no trust decision about would be a row nothing could ever use.
    """
    async with session() as s:
        peer = await s.get(Peer, node_id)
        if peer is None:
            return False
        # Replace rather than add: one pin per peer is the behaviour the CLI
        # offers, and a get-or-update keeps a re-pin of the same address from
        # colliding with a row left over from an earlier one.
        await s.execute(delete(PinnedAddress).where(PinnedAddress.node_id == node_id))
        s.add(PinnedAddress(node_id=node_id, host=host, port=port))
        await s.commit()
        _log.info("pinned %s at %s:%d", node_id.split("-")[0], host, port)
        return True


async def clear_address(node_id: str) -> bool:
    """Remove a peer's pinned addresses. False if the node is not paired."""
    async with session() as s:
        peer = await s.get(Peer, node_id)
        if peer is None:
            return False
        await s.execute(delete(PinnedAddress).where(PinnedAddress.node_id == node_id))
        await s.commit()
        _log.info("cleared pinned address for %s", node_id.split("-")[0])
        return True
