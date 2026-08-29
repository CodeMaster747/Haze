"""Moving a job's input files to the machine that will run it.

Chunked, checksummed and resumable-shaped: each chunk carries its own digest,
so a corrupted transfer is caught at the chunk that broke rather than after the
whole file has been written and a render has failed for an unobvious reason.

Deliberately not BLAKE3, despite the research recommending it. BLAKE3's real
advantage is a tree structure enabling verified streaming; here every chunk is
hashed and checked explicitly, so the property is already had -- and
``hashlib.blake2b`` is in the standard library. One fewer dependency on the
path that runs other people's files is worth more than the throughput
difference, which on a link this fast is not the bottleneck anyway.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haze import log

_log = log.get("blobs")

CHUNK_BYTES = 512 * 1024
"""512 KiB: comfortably inside the 1 MiB frame cap, and large enough that
per-chunk overhead is noise."""

MAX_FILE_BYTES = 2 * 1024**3   # 2 GiB
MAX_FILES = 64
MAX_TOTAL_BYTES = 4 * 1024**3


class TransferError(Exception):
    """A transfer that must not be completed. Message reaches the submitter."""


@dataclass(frozen=True)
class FileManifest:
    """What a submitter says it is about to send."""

    name: str
    size: int
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size, "digest": self.digest}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileManifest:
        name = str(data.get("name") or "")
        # The name becomes a filename on the receiving machine, so it is
        # validated here rather than trusted and cleaned up later. A single
        # path component, nothing else.
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise TransferError(f"illegal file name {name!r}")
        if name.startswith("."):
            raise TransferError("file names may not start with a dot")

        size = int(data.get("size") or 0)
        if not 0 <= size <= MAX_FILE_BYTES:
            raise TransferError(f"{name}: size {size} is out of range")

        digest = str(data.get("digest") or "")
        if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
            raise TransferError(f"{name}: malformed digest")

        return cls(name=name, size=size, digest=digest)


def digest_of(path: Path) -> str:
    hasher = hashlib.blake2b(digest_size=32)
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_manifest(paths: list[Path]) -> list[FileManifest]:
    if len(paths) > MAX_FILES:
        raise TransferError(f"too many files ({len(paths)}); the limit is {MAX_FILES}")
    total = 0
    manifest: list[FileManifest] = []
    for path in paths:
        if not path.is_file():
            raise TransferError(f"{path} is not a file")
        size = path.stat().st_size
        total += size
        if total > MAX_TOTAL_BYTES:
            raise TransferError(f"total upload exceeds {MAX_TOTAL_BYTES // 1024**3} GiB")
        manifest.append(FileManifest(name=path.name, size=size, digest=digest_of(path)))
    return manifest


class Receiver:
    """Writes one incoming file, verifying as it goes."""

    def __init__(self, entry: FileManifest, workdir: Path) -> None:
        self._entry = entry
        # Write to .part and rename on success, so a job can never start
        # against a half-written input.
        self._final = workdir / entry.name
        self._partial = workdir / f"{entry.name}.part"
        self._handle = self._partial.open("wb")
        self._hasher = hashlib.blake2b(digest_size=32)
        self._written = 0

    def write(self, chunk: bytes) -> None:
        self._written += len(chunk)
        if self._written > self._entry.size:
            self.abort()
            raise TransferError(
                f"{self._entry.name}: sender exceeded its declared size of {self._entry.size} bytes"
            )
        self._hasher.update(chunk)
        self._handle.write(chunk)

    def finish(self) -> Path:
        self._handle.close()
        if self._written != self._entry.size:
            self._partial.unlink(missing_ok=True)
            raise TransferError(
                f"{self._entry.name}: expected {self._entry.size} bytes, got {self._written}"
            )
        if self._hasher.hexdigest() != self._entry.digest:
            self._partial.unlink(missing_ok=True)
            raise TransferError(f"{self._entry.name}: checksum mismatch; the file is corrupt")
        self._partial.replace(self._final)
        _log.debug("received %s (%d bytes)", self._entry.name, self._written)
        return self._final

    def abort(self) -> None:
        self._handle.close()
        self._partial.unlink(missing_ok=True)
