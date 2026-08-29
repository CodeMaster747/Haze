"""Peer queries. The only module that decides who is trusted."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from haze import log
from haze.db.models import Peer
from haze.db.session import session

_log = log.get("db.peers")


async def all_peers() -> list[Peer]:
    async with session() as s:
        result = await s.scalars(select(Peer).order_by(Peer.display_name))
        return list(result)


async def get(node_id: str) -> Peer | None:
    async with session() as s:
        return await s.get(Peer, node_id)


async def by_public_key(public_key: bytes) -> Peer | None:
    async with session() as s:
        return await s.scalar(select(Peer).where(Peer.public_key == public_key))


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
        await s.delete(peer)
        await s.commit()
        _log.info("unpaired %s", node_id.split("-")[0])
        return True
