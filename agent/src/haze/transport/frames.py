"""Wire framing for the node-to-node control plane.

    ┌────────────┬─────────────────────┐
    │ 4-byte BE  │  JSON body          │
    │ length     │  (length bytes)      │
    └────────────┴─────────────────────┘

JSON rather than msgpack or CBOR: this channel carries heartbeats, job status
and pairing — a few hundred small messages a second at the very most. The
binary formats would buy throughput that is not the bottleneck, and cost the
ability to read a capture or a log line without a decoder. Bulk bytes never
come through here; they get a streamed HTTP body on the same connection pool
(M3), which is where framing overhead would actually matter.

The length cap is checked *before* allocating, so a peer -- or something
probing the port -- cannot make the agent reserve a gigabyte by claiming a
gigabyte is coming.
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

from haze import PROTOCOL_VERSION

_HEADER = struct.Struct(">I")
HEADER_SIZE = _HEADER.size

# Generous for JSON control messages, small enough to bound pre-auth memory.
# The largest legitimate frame is a pairing message carrying a PEM certificate,
# which is under 1 KiB.
MAX_FRAME_BYTES = 1 << 20  # 1 MiB


class FrameError(Exception):
    """Malformed frame. Always fatal for the connection: after a bad length
    prefix the stream position is unknown, so there is nothing to resync to."""


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read one frame. Raises :class:`asyncio.IncompleteReadError` at EOF."""
    header = await reader.readexactly(HEADER_SIZE)
    (length,) = _HEADER.unpack(header)

    if length > MAX_FRAME_BYTES:
        raise FrameError(f"frame of {length} bytes exceeds the {MAX_FRAME_BYTES} byte limit")
    if length == 0:
        raise FrameError("zero-length frame")

    body = await reader.readexactly(length)
    try:
        message = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FrameError(f"frame body is not valid JSON: {exc}") from exc

    if not isinstance(message, dict):
        raise FrameError(f"frame body must be a JSON object, got {type(message).__name__}")
    if "type" not in message:
        raise FrameError("frame body has no 'type'")
    return message


async def write_frame(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode()
    if len(body) > MAX_FRAME_BYTES:
        raise FrameError(f"refusing to send a {len(body)} byte frame")
    writer.write(_HEADER.pack(len(body)) + body)
    await writer.drain()


async def read_blob(reader: asyncio.StreamReader, max_bytes: int) -> bytes:
    """Read a length-prefixed binary payload.

    Sent immediately after a JSON frame that announces it. Raw bytes rather
    than base64 inside JSON: base64 costs 33% more on the wire and forces the
    whole payload through a JSON parser, which is the wrong tool for file
    contents.
    """
    header = await reader.readexactly(HEADER_SIZE)
    (length,) = _HEADER.unpack(header)
    if length > max_bytes:
        raise FrameError(f"blob of {length} bytes exceeds the {max_bytes} byte limit")
    return await reader.readexactly(length)


async def write_blob(writer: asyncio.StreamWriter, payload: bytes) -> None:
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


def message(kind: str, **fields: Any) -> dict[str, Any]:
    """Build a frame body.

    Every message carries the protocol version so a mismatched pair fails at the
    handshake with a clear error, rather than misparsing a field three messages
    later and producing something that looks like a bug in the application.
    """
    return {"type": kind, "v": PROTOCOL_VERSION, **fields}
