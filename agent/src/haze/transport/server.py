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
from pathlib import Path
from typing import Any

from haze import log
from haze.blobs import transfer as blobs
from haze.config import Config
from haze.db import peers as peer_db
from haze.identity.keys import Identity
from haze.jobs.executor import JobExecutor
from haze.jobs.spec import JobRecord, JobSpec
from haze.pairing.manager import PairingManager
from haze.transport import frames, tls
from haze.transport.handshake import HandshakeError, PeerIdentity, server_handshake

_log = log.get("transport.server")

IDLE_TIMEOUT_S = 300.0


def _containable_outputs(candidates: list[str], workdir: Path) -> list[Path]:
    """Keep only files that genuinely live inside this job's directory.

    The submitter names nothing here -- it asks for "the outputs" and receives
    exactly what the runtime reported. This is the check that a runtime bug, or
    a crafted Saved: line in a job's output, cannot turn into "send me
    /etc/passwd".
    """
    root = workdir.resolve()
    kept: list[Path] = []
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and root in path.resolve().parents:
            kept.append(path)
    return kept


class NodeServer:
    """Accepts connections from other Haze nodes."""

    def __init__(self, cfg: Config, identity: Identity, pairing: PairingManager,
                 executor: JobExecutor | None = None) -> None:
        self._cfg = cfg
        self._identity = identity
        self._pairing = pairing
        self._executor = executor
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

            if message.get("type") == "job_submit":
                # Handled inline rather than through _dispatch: a job produces a
                # stream of progress frames, not a single reply.
                await self._run_job_for(reader, writer, message, peer)
                continue

            reply = await self._dispatch(message, peer)
            if reply is None:
                return
            await frames.write_frame(writer, reply)

    async def _run_job_for(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        message: dict[str, Any],
        peer: PeerIdentity,
    ) -> None:
        """Accept a peer's job, then stream its progress back until it ends."""
        if self._executor is None:
            await frames.write_frame(
                writer, frames.message("job_rejected", reason="this node does not run jobs")
            )
            return

        try:
            spec = JobSpec.from_dict({**(message.get("spec") or {}), "submitted_by": peer.node_id})
        except (KeyError, TypeError, ValueError) as exc:
            await frames.write_frame(
                writer, frames.message("job_rejected", reason=f"malformed job spec: {exc}")
            )
            return

        # Stage any input files before admitting the job: a Blender render
        # cannot start without its .blend, and rejecting late would waste the
        # transfer.
        workdir = self._executor.workdir_for(spec.job_id)
        try:
            manifest = [blobs.FileManifest.from_dict(f) for f in (message.get("files") or [])]
            if manifest:
                workdir.mkdir(mode=0o700, parents=True, exist_ok=True)
                await self._receive_files(reader, writer, manifest, workdir)
        except blobs.TransferError as exc:
            await frames.write_frame(
                writer, frames.message("job_rejected", reason=f"file transfer failed: {exc}")
            )
            return

        record = self._executor.submit(spec)
        if record.state.value == "rejected":
            await frames.write_frame(
                writer, frames.message("job_rejected", reason=record.error, job=record.to_dict())
            )
            return

        await frames.write_frame(writer, frames.message("job_accepted", job=record.to_dict()))

        # Poll rather than subscribe: the executor already coalesces progress to
        # ~2.5 Hz, and polling at the same rate keeps the streaming path free of
        # a second callback registry to leak.
        last = ""
        while not record.state.terminal:
            await asyncio.sleep(0.4)
            current = f"{record.state}{record.progress.fraction}{record.progress.detail}"
            if current != last:
                last = current
                await frames.write_frame(
                    writer, frames.message("job_progress", job=record.to_dict())
                )

        await frames.write_frame(writer, frames.message("job_finished", job=record.to_dict()))

        # The submitter may now ask for the outputs. Optional: a job whose
        # result is 40 GiB of frames is often better left where it was made,
        # so fetching is the caller's decision rather than automatic.
        if record.outputs:
            await self._offer_outputs(reader, writer, record)
        _log.info(
            "job %s for %s finished: %s",
            spec.job_id[:8], peer.node_id.split("-")[0], record.state.value,
        )

    async def _offer_outputs(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, record: JobRecord
    ) -> None:
        """Send a finished job's outputs back, if the submitter asks."""
        try:
            request = await asyncio.wait_for(frames.read_frame(reader), 30)
        except (TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            return
        if request.get("type") != "job_fetch_outputs":
            return

        workdir = self._executor.workdir_for(record.spec.job_id) if self._executor else None
        if workdir is None:
            return

        try:
            # Off the event loop: resolving and stat-ing a few hundred rendered
            # frames is real filesystem work, not a couple of calls.
            paths = await asyncio.to_thread(_containable_outputs, record.outputs, workdir)
            manifest = await asyncio.to_thread(blobs.build_manifest, paths)
        except blobs.TransferError as exc:
            await frames.write_frame(writer, frames.message("job_outputs", error=str(exc)))
            return

        await frames.write_frame(
            writer, frames.message("job_outputs", files=[m.to_dict() for m in manifest])
        )
        for path in paths:
            with path.open("rb") as handle:
                while chunk := handle.read(blobs.CHUNK_BYTES):
                    await frames.write_frame(writer, frames.message("job_file_chunk", name=path.name))
                    await frames.write_blob(writer, chunk)
        _log.info("sent %d output file(s) for job %s", len(paths), record.spec.job_id[:8])

    async def _receive_files(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        manifest: list[blobs.FileManifest],
        workdir: Path,
    ) -> None:
        """Pull the declared files, verifying each chunk's digest."""
        total = sum(entry.size for entry in manifest)
        if total > blobs.MAX_TOTAL_BYTES:
            raise blobs.TransferError(
                f"declared {total // 1024**2} MiB; the limit is "
                f"{blobs.MAX_TOTAL_BYTES // 1024**3} GiB"
            )

        await frames.write_frame(
            writer, frames.message("job_files_wanted", names=[e.name for e in manifest])
        )

        for entry in manifest:
            receiver = blobs.Receiver(entry, workdir)
            try:
                remaining = entry.size
                while remaining > 0:
                    header = await asyncio.wait_for(frames.read_frame(reader), 120)
                    if header.get("type") != "job_file_chunk" or header.get("name") != entry.name:
                        raise blobs.TransferError(
                            f"expected a chunk of {entry.name}, got {header.get('type')!r}"
                        )
                    chunk = await frames.read_blob(reader, blobs.CHUNK_BYTES)
                    receiver.write(chunk)
                    remaining -= len(chunk)
                    if not chunk:
                        raise blobs.TransferError(f"{entry.name}: sender stopped early")
                receiver.finish()
            except (TimeoutError, asyncio.IncompleteReadError, ConnectionError) as exc:
                receiver.abort()
                raise blobs.TransferError(f"{entry.name}: connection lost mid-transfer") from exc
            except BaseException:
                receiver.abort()
                raise

        _log.info("received %d file(s) for a job", len(manifest))

    async def _dispatch(self, message: dict[str, Any], peer: PeerIdentity) -> dict[str, Any] | None:
        kind = message.get("type")
        if kind == "ping":
            return frames.message("pong", echo=message.get("echo"))
        if kind == "capabilities":
            # What this node can do, so a submitter can choose sensibly. The
            # scheduler in M4 consumes exactly this.
            from haze.jobs import runtimes as rt

            return frames.message(
                "capabilities",
                runtimes=rt.available_names(),
                caps=self._executor.caps.to_dict() if self._executor else None,
            )
        if kind == "bye":
            return None
        _log.warning("unknown message %r from %s", kind, peer.node_id.split("-")[0])
        return frames.message("error", reason="unknown_type", detail=f"unsupported message {kind!r}")
