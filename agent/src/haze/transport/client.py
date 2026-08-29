"""Dialling another Haze node."""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haze import log
from haze.blobs import transfer as blobs
from haze.config import Config
from haze.db import peers as peer_db
from haze.identity.keys import Identity
from haze.jobs.spec import JobSpec
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


async def submit_job_to(
    node_id: str,
    spec: JobSpec,
    identity: Identity,
    cfg: Config,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    files: list[Path] | None = None,
    fetch_into: Path | None = None,
) -> dict[str, Any]:
    """Run a job on a paired peer and stream its progress back.

    Returns the finished job record. Raises ConnectError with a message written
    for the person who submitted it.
    """
    peer = await peer_db.get(node_id)
    if peer is None:
        raise ConnectError(f"not paired with {node_id.split('-')[0]}")
    if not peer.last_host or not peer.last_port:
        raise ConnectError(
            f"no known address for {peer.display_name} yet -- wait for it to connect once"
        )

    async with connect(
        peer.last_host, peer.last_port, identity, cfg.node_name, cfg.node_port,
        expected_public_key=peer.public_key, expected_cert=peer.cert_der,
    ) as conn:
        hello = await conn.recv(timeout=10.0)
        if hello.get("type") != "auth_ok":
            raise ConnectError(str(hello.get("detail") or hello.get("reason") or "refused"))

        manifest = blobs.build_manifest(files or [])
        await conn.send(
            frames.message(
                "job_submit",
                spec=spec.to_dict(),
                files=[entry.to_dict() for entry in manifest],
            )
        )

        if manifest:
            wanted = await conn.recv(timeout=30.0)
            if wanted.get("type") == "job_rejected":
                raise ConnectError(f"{peer.display_name} refused: {wanted.get('reason')}")
            if wanted.get("type") != "job_files_wanted":
                raise ConnectError(f"unexpected reply {wanted.get('type')!r} to a file offer")
            await _send_files(conn, files or [])

        # No overall deadline here: the job's own wall_seconds bounds it on the
        # far side, and a client-side timer would abandon a legitimately long
        # render while it was still making progress.
        while True:
            message = await conn.recv(timeout=spec.resources.wall_seconds + 60)
            kind = message.get("type")

            if kind == "job_rejected":
                raise ConnectError(f"{peer.display_name} refused the job: {message.get('reason')}")
            if kind == "job_accepted" or kind == "job_progress":
                if on_progress:
                    on_progress(dict(message.get("job") or {}))
            elif kind == "job_finished":
                final = dict(message.get("job") or {})
                if fetch_into is not None and final.get("outputs"):
                    final["outputs"] = await _fetch_outputs(conn, fetch_into)
                return final
            elif kind == "error":
                raise ConnectError(str(message.get("detail") or message.get("reason")))


async def _fetch_outputs(conn: Connection, destination: Path) -> list[str]:
    """Pull a finished job's outputs back to this machine."""
    await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
    await conn.send(frames.message("job_fetch_outputs"))

    header = await conn.recv(timeout=60.0)
    if header.get("type") != "job_outputs" or header.get("error"):
        _log.warning("could not fetch outputs: %s", header.get("error") or header.get("type"))
        return []

    manifest = [blobs.FileManifest.from_dict(f) for f in (header.get("files") or [])]
    written: list[str] = []
    for entry in manifest:
        receiver = blobs.Receiver(entry, destination)
        try:
            remaining = entry.size
            while remaining > 0:
                chunk_header = await conn.recv(timeout=120.0)
                if chunk_header.get("type") != "job_file_chunk":
                    raise blobs.TransferError(f"expected a chunk, got {chunk_header.get('type')!r}")
                chunk = await frames.read_blob(conn.reader, blobs.CHUNK_BYTES)
                receiver.write(chunk)
                remaining -= len(chunk)
            written.append(str(receiver.finish()))
        except (blobs.TransferError, TimeoutError, ConnectionError) as exc:
            receiver.abort()
            _log.warning("output %s did not transfer: %s", entry.name, exc)
    return written


async def _send_files(conn: Connection, paths: list[Path]) -> None:
    """Stream each file as announce-then-blob pairs."""
    for path in paths:
        with path.open("rb") as handle:
            while chunk := handle.read(blobs.CHUNK_BYTES):
                await conn.send(frames.message("job_file_chunk", name=path.name))
                await frames.write_blob(conn.writer, chunk)


async def peer_capabilities(node_id: str, identity: Identity, cfg: Config) -> dict[str, Any]:
    """Ask a peer what it can run. The scheduler's input in M4."""
    peer = await peer_db.get(node_id)
    if peer is None or not peer.last_host or not peer.last_port:
        raise ConnectError("peer is not reachable yet")

    async with connect(
        peer.last_host, peer.last_port, identity, cfg.node_name, cfg.node_port,
        expected_public_key=peer.public_key, expected_cert=peer.cert_der,
    ) as conn:
        await conn.recv(timeout=10.0)   # auth_ok
        await conn.send(frames.message("capabilities"))
        reply = await conn.recv(timeout=10.0)
        return {"runtimes": reply.get("runtimes") or [], "caps": reply.get("caps")}


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
