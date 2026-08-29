"""Local persistent state.

SQLite, one file per node, in the state directory. Nothing here is shared
between nodes: each agent's view of the network is its own.

No Alembic in v1. There is exactly one schema, it is created on startup, and a
personal tool should be able to recover from a schema problem by deleting a
file and re-pairing rather than by running a migration. `schema_version` exists
so that when migrations do become worth it, there is something to migrate from.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Peer(Base):
    """A node this one has paired with.

    The row is the trust decision. If a peer is in this table, its certificate
    goes into the TLS trust bundle and its public key is accepted at handshake;
    if it is not, the connection is refused. Unpairing is a DELETE.
    """

    __tablename__ = "peers"
    __table_args__ = (UniqueConstraint("public_key", name="uq_peers_public_key"),)

    node_id: Mapped[str] = mapped_column(String(71), primary_key=True)

    public_key: Mapped[bytes] = mapped_column(LargeBinary(32))
    """Raw 32-byte Ed25519 key. The authoritative identity — the certificate can
    be regenerated, this cannot change without the peer becoming a stranger."""

    cert_der: Mapped[bytes] = mapped_column(LargeBinary)
    """Most recently seen certificate, for the TLS trust bundle."""

    display_name: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(64), default="")
    agent_version: Mapped[str] = mapped_column(String(32), default="")

    # Last address that worked, so a reconnect can skip discovery. Advisory
    # only: addresses change, and identity never depends on them.
    last_host: Mapped[str] = mapped_column(String(255), default="")
    last_port: Mapped[int] = mapped_column(Integer, default=0)

    paired_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )

    # Bumped whenever this peer's permissions change. A grant carrying a lower
    # generation is stale and refused, which makes "revoke now" instant without
    # needing an online revocation service (M3).
    policy_generation: Mapped[int] = mapped_column(Integer, default=1)


class Meta(Base):
    """Single-row key/value table. Currently just the schema version."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
