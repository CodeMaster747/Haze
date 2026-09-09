"""Dialling another Haze node."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import ssl
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haze import log
from haze.blobs import transfer as blobs
from haze.config import Config
from haze.db import peers as peer_db
from haze.db.models import Peer, PinnedAddress
from haze.identity.keys import Identity
from haze.jobs.spec import JobSpec
from haze.pairing import sas
from haze.transport import frames, tls
from haze.transport.handshake import HandshakeError, PeerIdentity, client_handshake

_log = log.get("transport.client")

CONNECT_TIMEOUT_S = 8.0

# Smallest dial worth starting. Below this a connect cannot distinguish a slow
# link from a dead one, so the attempt would only produce a misleading timeout.
MIN_ATTEMPT_S = 1.5

# `probe_peers` wraps every capability call in asyncio.wait_for(..., 4.0). A
# budget above that would be cancelled mid-dial and the fallback address would
# never be tried at all -- the pin would work for ping and jobs and silently do
# nothing for the scheduler.
CAPABILITIES_BUDGET_S = 3.5

# The dashboard's POST /peers/{id}/ping has no timeout of its own, so this is
# what a user waits for when they click it.
PING_BUDGET_S = 10.0

# Tailscale hands out addresses from the RFC 6598 shared range and its own
# unique-local v6 prefix. Recognising them is only ever used to word an error
# message; nothing about trust or routing depends on it.
_OVERLAY_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)

# Spelled out rather than using `is_private`, which answers a broader question
# ("not globally reachable") than the one being asked here. It is True for the
# documentation ranges and, depending on the Python version, disagrees with
# itself about the shared range above -- so leaning on it would make the hint
# unpredictable across interpreters.
_LAN_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class ConnectError(Exception):
    """Could not reach or authenticate the peer. Message is user-facing.

    ``kind`` lets a caller trying several addresses tell "nothing answered"
    from "something answered with the wrong certificate" without matching on
    message text. ``brief`` is the one-line form used when several failures
    have to be reported together.
    """

    def __init__(self, message: str, *, kind: str = "unreachable", brief: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        """One of "unreachable", "timeout", "tls", "identity"."""
        self.brief = brief or message


def _timeout_hint(host: str) -> str:
    """Why a connection to ``host`` might have timed out.

    Client isolation is a real and common cause on a LAN, and a useless thing
    to say about a machine reached over an overlay network or the open
    internet -- it sends the user to their router settings for a problem that
    is not there.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A DNS name. It resolved (we got as far as connecting), but nothing
        # about the address tells us which network it is on.
        return ("Is the agent running there, and is the port open through any firewall "
                "in between?")

    if any(address in net for net in _OVERLAY_NETS):
        return ("That is an overlay address. Is Tailscale up on both machines? "
                "`tailscale status` on each will say.")
    if address.is_loopback or any(address in net for net in _LAN_NETS):
        return ("Is the agent running there, and is the port reachable? Some access points "
                "isolate clients from each other, which blocks this even when both machines "
                "are on the same WiFi.")
    return ("Is the agent running there, and is the port reachable from outside its network? "
            "A public address usually needs a firewall rule or port forward.")


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
    timeout_s: float = CONNECT_TIMEOUT_S,
) -> AsyncIterator[Connection]:
    """Open an authenticated connection to a node.

    Pass ``expected_public_key`` for a known peer so the pin is enforced; pass
    ``None`` only when pairing, where the peer is unknown by definition.
    """
    context = tls.client_context(expected_cert)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context, server_hostname=""),
            timeout_s,
        )
    except TimeoutError as exc:
        # The deadline named here is the one actually used, not the module
        # default: when several addresses share a budget they each get less.
        raise ConnectError(
            f"{host}:{port} did not respond within {timeout_s:.0f}s. {_timeout_hint(host)}",
            kind="timeout",
            brief=f"no response in {timeout_s:.0f}s",
        ) from exc
    except ssl.SSLCertVerificationError as exc:
        # The pinned certificate did not match what the far end presented.
        # OpenSSL's wording ("self-signed certificate in certificate chain")
        # describes every Haze certificate and explains nothing, so say what
        # actually happened.
        raise ConnectError(
            f"{host}:{port} presented a certificate that does not match the one recorded "
            f"when you paired. Either it is a different machine, or its identity was reset "
            f"(deleting ~/.haze does that). Re-pair to trust it again. [{exc.verify_message}]",
            kind="identity",
            brief="presented a different certificate",
        ) from exc
    except ssl.SSLError as exc:
        raise ConnectError(
            f"TLS handshake with {host}:{port} failed: {exc}", kind="tls", brief=f"TLS failed: {exc}"
        ) from exc
    except OSError as exc:
        raise ConnectError(
            f"could not reach {host}:{port}: {exc}",
            brief=str(exc.strerror or exc),
        ) from exc

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
        # An identity failure like a certificate mismatch, just detected one
        # layer up: this is where the expected_public_key pin is enforced.
        raise ConnectError(str(exc), kind="identity") from exc
    finally:
        # BaseException, not Exception: CancelledError is not an Exception, and
        # `probe_peers` cancels these routinely. Letting a cancellation escape
        # from here would replace whatever error the caller was already
        # reporting with a bare CancelledError.
        with contextlib.suppress(BaseException):
            writer.close()
            await writer.wait_closed()


@dataclass(frozen=True, slots=True)
class Address:
    """One place a peer might be reachable, and where that belief came from."""

    host: str
    port: int
    source: str
    """"pinned" (the user said so) or "last seen" (observed traffic)."""

    def __str__(self) -> str:
        return f"{self.host}:{self.port} ({self.source})"


async def peer_addresses(peer: Peer, pins: list[PinnedAddress] | None = None) -> list[Address]:
    """Every address worth trying for a peer, best first.

    Pinned addresses lead because they are the user's stated intent; the
    last-observed address follows as the fallback that needs no configuration.
    Pass ``pins`` when iterating many peers to avoid a query each.
    """
    if pins is None:
        pins = await peer_db.pinned(peer.node_id)

    found: list[Address] = [Address(pin.host, pin.port, "pinned") for pin in pins]
    if peer.last_host and peer.last_port:
        found.append(Address(peer.last_host, peer.last_port, "last seen"))

    # Dedupe textually, keeping the first (and so the higher-priority) entry.
    # This does not catch a name and an address that resolve to one machine --
    # pinning `box.local` alongside a last-seen 192.168.1.5 costs two dials to
    # learn one fact. Resolving to compare would cost a lookup on every dial.
    seen: set[tuple[str, int]] = set()
    unique: list[Address] = []
    for address in found:
        key = (address.host, address.port)
        if key not in seen:
            seen.add(key)
            unique.append(address)
    return unique


def _no_address_error(peer: Peer) -> ConnectError:
    return ConnectError(
        f"no known address for {peer.display_name} yet -- wait for it to connect once, "
        f"or set one with `haze address {peer.display_name} --set <host>`."
    )


def _dial_failure(peer: Peer, failures: list[tuple[Address, ConnectError]]) -> ConnectError:
    """Turn several failed dials into one message.

    A single failure is re-raised untouched. That is the overwhelmingly common
    case, its wording is already written for a user, and both `routes_jobs` and
    `routes_pairing` pipe this string straight into a UI field sized for a
    sentence -- concatenating two of them would blow it out.
    """
    if len(failures) == 1:
        return failures[0][1]

    # An address that answered with the wrong certificate is a more actionable
    # fact than several that did not answer at all, so it leads.
    identity = next((exc for _, exc in failures if exc.kind == "identity"), None)
    lines = "\n".join(f"  {address} -- {exc.brief}" for address, exc in failures)
    detail = f"\n{identity}" if identity else ""
    return ConnectError(
        f"could not reach {peer.display_name} at any known address:\n{lines}{detail}",
        kind=identity.kind if identity else "unreachable",
    )


@asynccontextmanager
async def connect_to_peer(
    peer: Peer,
    identity: Identity,
    cfg: Config,
    budget_s: float | None = None,
    pins: list[PinnedAddress] | None = None,
) -> AsyncIterator[Connection]:
    """Connect to a paired peer, trying its known addresses in order.

    A peer can be reachable at more than one address -- a LAN address and an
    overlay address, say -- and which one works depends on where the machine
    currently is. Dialling only the last-observed address means a laptop that
    left the house stops being reachable even though its pinned address is
    fine.

    ``budget_s`` bounds the whole attempt, not each dial, because the caller
    is the only one that knows how long its own caller will wait.
    """
    candidates = await peer_addresses(peer, pins)
    if not candidates:
        raise _no_address_error(peer)

    deadline = time.monotonic() + (budget_s or CONNECT_TIMEOUT_S * len(candidates))
    failures: list[tuple[Address, ConnectError]] = []

    async with AsyncExitStack() as stack:
        for index, address in enumerate(candidates):
            # Fair share of what is left, capped at the normal timeout. A plain
            # `min(CONNECT_TIMEOUT_S, remaining)` would let a black-holed first
            # address eat most of the budget -- and the first address is the
            # pinned one, the one a user typed and so the likelier to be wrong.
            # Dividing also hands unspent time back when a dial fails fast.
            remaining = deadline - time.monotonic()
            attempt = min(CONNECT_TIMEOUT_S, remaining / (len(candidates) - index))
            if attempt < MIN_ATTEMPT_S:
                failures.append((address, ConnectError("not tried: out of time")))
                continue
            try:
                conn = await stack.enter_async_context(
                    connect(
                        address.host,
                        address.port,
                        identity,
                        cfg.node_name,
                        cfg.node_port,
                        expected_public_key=peer.public_key,
                        expected_cert=peer.cert_der,
                        timeout_s=attempt,
                    )
                )
            except ConnectError as exc:
                # Falling through on an identity failure too. Authentication is
                # bound to the public key, never to the address, so trying
                # another address cannot let an impostor in -- it can only
                # reach the real peer. Aborting instead would mean a pinned
                # address later reassigned to some other machine takes the peer
                # offline permanently, which is this feature's *expected*
                # decay, not an attack.
                failures.append((address, exc))
                continue

            _log.debug("reached %s at %s", peer.display_name, address)
            # INVARIANT: this yield must stay outside the `except` above, with
            # nothing that can raise ConnectError between them. Callers raise
            # ConnectError from inside this block (a refused job, a mid-job
            # disconnect); catching one here would dial the next address and
            # yield a second time -- "generator didn't stop after athrow()" --
            # replacing the user's real error with an internal traceback.
            yield conn
            return

        raise _dial_failure(peer, failures)


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

    # No budget: the person who submitted this is already committed, and the
    # job's own wall clock bounds what follows.
    async with connect_to_peer(peer, identity, cfg) as conn:
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
            try:
                message = await conn.recv(timeout=spec.resources.wall_seconds + 60)
            except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError) as exc:
                # The peer vanished mid-job -- agent killed, machine slept, cable
                # pulled. asyncio's own message here is "0 bytes read on a total
                # of 4 expected bytes", which tells the person who submitted the
                # job nothing at all about what happened or what to do.
                raise ConnectError(
                    f"{peer.display_name} disconnected while running this job. "
                    f"Its agent may have stopped or the machine gone to sleep — "
                    f"the work is lost and will need resubmitting."
                ) from exc
            except TimeoutError as exc:
                raise ConnectError(
                    f"{peer.display_name} stopped responding while running this job "
                    f"(no message for {spec.resources.wall_seconds + 60}s)."
                ) from exc
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
    if peer is None:
        raise ConnectError("peer is not reachable yet")

    async with connect_to_peer(peer, identity, cfg, budget_s=CAPABILITIES_BUDGET_S) as conn:
        await conn.recv(timeout=10.0)   # auth_ok
        await conn.send(frames.message("capabilities"))
        reply = await conn.recv(timeout=10.0)
        return {"runtimes": reply.get("runtimes") or [], "caps": reply.get("caps")}


async def ping_peer(node_id: str, identity: Identity, cfg: Config) -> tuple[bool, str]:
    """Reachability check against a paired peer. Returns (ok, detail)."""
    peer = await peer_db.get(node_id)
    if peer is None:
        return False, "not paired"

    # The "no known address" case is now connect_to_peer's to report, and it
    # arrives here as a ConnectError like any other. It must never fall back to
    # our own node port: before the port-advertising handshake landed, that bug
    # made a node ping itself and report success.
    try:
        async with connect_to_peer(peer, identity, cfg, budget_s=PING_BUDGET_S) as conn:
            reply = await conn.recv(timeout=10.0)
            if reply.get("type") != "auth_ok":
                return False, str(reply.get("detail") or reply.get("reason") or "refused")
            ok = await conn.ping()
            return ok, "ok" if ok else "no pong"
    except ConnectError as exc:
        return False, str(exc)
