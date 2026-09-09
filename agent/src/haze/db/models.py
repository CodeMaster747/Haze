"""Local persistent state.

SQLite, one file per node, in the state directory. Nothing here is shared
between nodes: each agent's view of the network is its own.

No Alembic in v1. There is exactly one schema, it is created on startup, and a
personal tool should be able to recover from a schema problem by deleting a
file and re-pairing rather than by running a migration. `schema_version` exists
so that when migrations do become worth it, there is something to migrate from.

When to bump SCHEMA_VERSION
---------------------------
Only for a change `create_all` cannot perform on an existing database: a new,
changed or dropped column on an existing table, a type change, a constraint
change. Those need `ALTER TABLE`, which is not emitted, so without a bump the
agent would fail at first use with `no such column` instead of saying what is
wrong.

Adding a whole *table* is not such a change. `create_all` creates missing
tables, so an older database gains it on the next start; an older agent reading
a newer database simply ignores a table it does not know about. Bumping for
that would cost every user every pairing (the check in session.py is `!=`, and
there is no migration code to run) in exchange for nothing.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
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


class PinnedAddress(Base):
    """An address the user pinned for a peer. Observed traffic never overwrites it.

    `Peer.last_host` records where a peer last connected *from*, and
    :func:`haze.transport.server` rewrites it on every inbound session. That is
    the right behaviour for a fact about observed traffic and the wrong
    behaviour for a user's stated preference: a machine reachable both on the
    LAN and over an overlay network would flip-flop between the two depending
    on which path it last dialled in on. A pin is the user saying "reach it
    here", and nothing but the user clears it.

    A separate table rather than columns on `peers` so that an existing
    database gains it through `create_all`, with no schema bump and no re-pair
    -- see the module docstring.

    The primary key is composite so the table can hold several addresses per
    peer. `haze address --set` currently keeps one (replace-all), but pinning
    both an overlay and a LAN address is the obvious next request, and with a
    `node_id`-only key satisfying it would mean altering an existing table --
    exactly the migration this design exists to avoid.
    """

    __tablename__ = "peer_addresses"

    node_id: Mapped[str] = mapped_column(
        String(71), ForeignKey("peers.node_id", ondelete="CASCADE"), primary_key=True
    )
    host: Mapped[str] = mapped_column(String(255), primary_key=True)
    port: Mapped[int] = mapped_column(Integer, primary_key=True)

    set_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Meta(Base):
    """Single-row key/value table. Currently just the schema version."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
