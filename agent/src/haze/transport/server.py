"""The node-to-node listener.

Unlike the dashboard API, this one binds to all interfaces -- other machines
have to reach it. Everything that makes that safe happens above TLS: an
unpaired peer gets past the handshake only while the user has explicitly armed
pairing, and even then it is the user comparing the SAS on two screens that
decides.

Runs on raw asyncio rather than uvicorn because uvicorn cannot expose the peer
certificate to the application, and the peer certificate is a node's identity.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from haze import log
from haze.config import Config
from haze.db import peers as peer_db
from haze.identity.keys import Identity
from haze.pairing.manager import PairingManager
from haze.transport import frames, tls
from haze.transport.handshake import HandshakeError, PeerIdentity, server_handshake

_log = log.get("transport.server")

IDLE_TIMEOUT_S = 300.0


class NodeServer:
    """Accepts connections from other Haze nodes."""

    def __init__(self, cfg: Config, identity: Identity, pairing: PairingManager) -> None:
        self._cfg = cfg
        self._identity = identity
        self._pairing = pairing
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        context = tls.pairing_server_context()
        self._server = await asyncio.start_server(
            self._handle, host="0.0.0.0", port=self._cfg.node_port, ssl=context  # noqa: S104
        )
        _log.info("node listener on 0.0.0.0:%d (node %s)", self._cfg.node_port,
                  self._identity.short_id)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        with contextlib.suppress(Exception):
            await self._server.wait_closed()
        self._server = None

    # --- connection handling ------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        host = addr[0] if addr else "?"
        peer: PeerIdentity | None = None
        try:
            peer = await server_handshake(
                reader, writer, self._identity, self._cfg.node_name, self._cfg.node_port
            )
            known = await peer_db.by_public_key(peer.public_key)

            if known is not None:
                await peer_db.touch(peer.node_id, host=host, port=peer.node_port)
                await frames.write_frame(writer, frames.message("auth_ok", paired=True))
                _log.info("session with %s (%s)", known.display_name, peer.node_id.split("-")[0])
                await self._serve_session(reader, writer, peer)
            elif self._pairing.is_armed:
                await self._serve_pairing(reader, writer, peer, host)
            else:
                # Deliberately specific. "Unknown peer" with no hint is the kind
                # of error that costs an hour; naming the remedy costs nothing
                # and leaks nothing an attacker does not already know.
                await frames.write_frame(
                    writer,
                    frames.message(
                        "error",
                        reason="not_paired",
                        detail="This node has not paired with you, and pairing is not armed. "
                               "Run `haze pair --serve` on it first.",
                    ),
                )
                _log.warning("refused unpaired peer %s from %s", peer.node_id.split("-")[0], host)

        except HandshakeError as exc:
            _log.warning("handshake failed from %s: %s", host, exc)
            with contextlib.suppress(Exception):
                await frames.write_frame(writer, frames.message("error", reason="handshake", detail=str(exc)))
        except (TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            _log.debug("connection from %s ended", host)
        except frames.FrameError as exc:
            _log.warning("bad frame from %s: %s", host, exc)
        except Exception:
            _log.exception("unhandled error serving %s", host)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    # --- pairing ------------------------------------------------------------

    async def _serve_pairing(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: PeerIdentity,
        host: str,
    ) -> None:
        pending = self._pairing.open_request(peer)
        await frames.write_frame(
            writer,
            frames.message(
                "pair_pending",
                session_id=pending.session_id,
                sas_digits=pending.sas_digits,
                sas_words=pending.sas_words,
            ),
        )

        # Both users must say yes, and neither waits on the other: this side's
        # dialog and the initiator's prompt resolve independently, and pairing
        # succeeds only if both come back confirmed.
        local_task = asyncio.create_task(self._pairing.wait_for_decision(pending.session_id))
        remote_task = asyncio.create_task(self._read_remote_decision(reader))
        try:
            local, remote = await asyncio.gather(local_task, remote_task)
        finally:
            for task in (local_task, remote_task):
                if not task.done():
                    task.cancel()

        if local != "confirmed" or not remote:
            reason = "declined_here" if local != "confirmed" else "declined_there"
            await frames.write_frame(writer, frames.message("pair_failed", reason=reason))
            _log.info("pairing with %s not completed (%s)", peer.node_id.split("-")[0], reason)
            self._pairing.forget(pending.session_id)
            return

        await peer_db.upsert(
            node_id=peer.node_id,
            public_key=peer.public_key,
            cert_der=peer.cert_der,
            display_name=peer.display_name,
            platform=peer.platform,
            agent_version=peer.agent_version,
            host=host,
            port=peer.node_port,
        )
        await frames.write_frame(writer, frames.message("pair_ok"))
        self._pairing.forget(pending.session_id)
        # One successful pairing closes the window. Leaving it armed would mean
        # a second, unnoticed device could follow through the same opening.
        self._pairing.disarm()

    async def _read_remote_decision(self, reader: asyncio.StreamReader) -> bool:
        try:
            message = await frames.read_frame(reader)
        except (asyncio.IncompleteReadError, ConnectionError, frames.FrameError):
            return False
        return message.get("type") == "pair_decision" and message.get("confirmed") is True

    # --- established session ------------------------------------------------

    async def _serve_session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, peer: PeerIdentity
    ) -> None:
        """Message loop for an authenticated peer.

        M1 speaks only ping/pong -- enough to prove the channel works end to
        end. Job submission and telemetry exchange land here in M2 and M3.
        """
        while True:
            try:
                message = await asyncio.wait_for(frames.read_frame(reader), IDLE_TIMEOUT_S)
            except TimeoutError:
                _log.debug("idle timeout for %s", peer.node_id.split("-")[0])
                return

            reply = await self._dispatch(message, peer)
            if reply is None:
                return
            await frames.write_frame(writer, reply)

    async def _dispatch(self, message: dict[str, Any], peer: PeerIdentity) -> dict[str, Any] | None:
        kind = message.get("type")
        if kind == "ping":
            return frames.message("pong", echo=message.get("echo"))
        if kind == "bye":
            return None
        _log.warning("unknown message %r from %s", kind, peer.node_id.split("-")[0])
        return frames.message("error", reason="unknown_type", detail=f"unsupported message {kind!r}")
