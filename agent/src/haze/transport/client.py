"""Dialling another Haze node."""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from haze import log
from haze.config import Config
from haze.db import peers as peer_db
from haze.identity.keys import Identity
from haze.pairing import sas
from haze.transport import frames, tls
from haze.transport.handshake import HandshakeError, PeerIdentity, client_handshake

_log = log.get("transport.client")

CONNECT_TIMEOUT_S = 8.0


class ConnectError(Exception):
    """Could not reach or authenticate the peer. Message is user-facing."""


@dataclass
class Connection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    peer: PeerIdentity

    async def send(self, message: dict[str, Any]) -> None:
        await frames.write_frame(self.writer, message)

    # ASYNC109: ruff prefers callers to wrap in asyncio.timeout(). Here the
    # timeout is part of the protocol -- each exchange has its own sensible
    # deadline (10s for a ping, 180s for a human confirming a pairing) and
    # pushing that to every call site would spread protocol knowledge around.
    async def recv(self, timeout: float = 30.0) -> dict[str, Any]:  # noqa: ASYNC109
        return await asyncio.wait_for(frames.read_frame(self.reader), timeout)

    async def ping(self, echo: str = "ping") -> bool:
        await self.send(frames.message("ping", echo=echo))
        reply = await self.recv(timeout=10.0)
        return reply.get("type") == "pong" and reply.get("echo") == echo


@asynccontextmanager
async def connect(
    host: str,
    port: int,
    identity: Identity,
    node_name: str,
    node_port: int,
    expected_public_key: bytes | None = None,
    expected_cert: bytes | None = None,
) -> AsyncIterator[Connection]:
    """Open an authenticated connection to a node.

    Pass ``expected_public_key`` for a known peer so the pin is enforced; pass
    ``None`` only when pairing, where the peer is unknown by definition.
    """
    context = tls.client_context(expected_cert)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=""),
            CONNECT_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise ConnectError(
            f"{host}:{port} did not respond within {CONNECT_TIMEOUT_S:.0f}s. Is the agent "
            f"running there, and is the port reachable? Some access points isolate clients "
            f"from each other, which blocks this even when both machines are on the same WiFi."
        ) from exc
    except ssl.SSLCertVerificationError as exc:
        # The pinned certificate did not match what the far end presented.
        # OpenSSL's wording ("self-signed certificate in certificate chain")
        # describes every Haze certificate and explains nothing, so say what
        # actually happened.
        raise ConnectError(
            f"{host}:{port} presented a certificate that does not match the one recorded "
            f"when you paired. Either it is a different machine, or its identity was reset "
            f"(deleting ~/.haze does that). Re-pair to trust it again. [{exc.verify_message}]"
        ) from exc
    except ssl.SSLError as exc:
        raise ConnectError(f"TLS handshake with {host}:{port} failed: {exc}") from exc
    except OSError as exc:
        raise ConnectError(f"could not reach {host}:{port}: {exc}") from exc

    try:
        peer = await client_handshake(
            reader,
            writer,
            identity,
            node_name,
            node_port,
            writer.get_extra_info("ssl_object"),
            expected_public_key,
        )
        yield Connection(reader=reader, writer=writer, peer=peer)
    except HandshakeError as exc:
        raise ConnectError(str(exc)) from exc
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def pair(
    host: str,
    port: int,
    identity: Identity,
    node_name: str,
    node_port: int,
    confirm: Callable[[str, list[str], PeerIdentity], Awaitable[bool]],
) -> PeerIdentity:
    """Initiate pairing with the node at ``host:port``.

    ``confirm`` is called with the SAS digits, the SAS words and the peer's
    details, and must return whether *this* user confirmed. The other node asks
    its own user the same question independently; pairing completes only if
    both say yes.
    """
    async with connect(host, port, identity, node_name, node_port) as conn:
        message = await conn.recv(timeout=15.0)

        if message.get("type") == "error":
            raise ConnectError(str(message.get("detail") or message.get("reason")))
        if message.get("type") == "auth_ok":
            raise ConnectError(
                f"already paired with {conn.peer.display_name} "
                f"({conn.peer.node_id.split('-')[0]}). Run `haze unpair` first to re-pair."
            )
        if message.get("type") != "pair_pending":
            raise ConnectError(f"unexpected reply {message.get('type')!r}")

        # Recompute rather than trusting the digits the peer sent. If the two
        # ever disagreed, showing the peer's number would defeat the entire
        # point of comparing them.
        digits = sas.digits(identity.public_key, conn.peer.public_key)
        words = sas.words(identity.public_key, conn.peer.public_key)
        if not sas.matches(digits, str(message.get("sas_digits", ""))):
            raise ConnectError(
                "the other node computed a different confirmation code. Something is "
                "intercepting this connection -- do not continue."
            )

        confirmed = await confirm(digits, words, conn.peer)
        await conn.send(frames.message("pair_decision", confirmed=confirmed))
        if not confirmed:
            raise ConnectError("pairing declined here")

        result = await conn.recv(timeout=180.0)
        if result.get("type") != "pair_ok":
            reason = str(result.get("reason", "unknown"))
            raise ConnectError(
                "the other node declined the pairing"
                if reason == "declined_here"
                else f"pairing did not complete ({reason})"
            )

        await peer_db.upsert(
            node_id=conn.peer.node_id,
            public_key=conn.peer.public_key,
            cert_der=conn.peer.cert_der,
            display_name=conn.peer.display_name,
            platform=conn.peer.platform,
            agent_version=conn.peer.agent_version,
            host=host,
            # The port we dialled, not the one it advertises: this is the address
            # that demonstrably worked from here.
            port=port,
        )
        return conn.peer


async def ping_peer(node_id: str, identity: Identity, cfg: Config) -> tuple[bool, str]:
    """Reachability check against a paired peer. Returns (ok, detail)."""
    peer = await peer_db.get(node_id)
    if peer is None:
        return False, "not paired"
    if not peer.last_host or not peer.last_port:
        # Before the port-advertising handshake landed, this was silently
        # falling back to *our own* node port and pinging ourselves.
        return False, "no known address for this peer yet -- wait for it to connect once"

    try:
        async with connect(
            peer.last_host,
            peer.last_port,
            identity,
            cfg.node_name,
            cfg.node_port,
            expected_public_key=peer.public_key,
            expected_cert=peer.cert_der,
        ) as conn:
            reply = await conn.recv(timeout=10.0)
            if reply.get("type") != "auth_ok":
                return False, str(reply.get("detail") or reply.get("reason") or "refused")
            ok = await conn.ping()
            return ok, "ok" if ok else "no pong"
    except ConnectError as exc:
        return False, str(exc)
