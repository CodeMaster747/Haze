"""File transfer integrity and the name allowlist.

A manifest entry's `name` becomes a filename on the receiving machine, so it is
validated on arrival rather than trusted and cleaned up afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from haze.blobs import transfer

_VALID_DIGEST = "a" * 64


def _entry(name: str = "scene.blend", size: int = 4, digest: str | None = None) -> dict[str, object]:
    # `digest if digest is not None`, not `digest or` -- the latter would
    # silently substitute the valid default for the empty string this test
    # specifically wants to reject.
    return {
        "name": name,
        "size": size,
        "digest": _VALID_DIGEST if digest is None else digest,
    }


@pytest.mark.parametrize(
    "name",
    [
        "../escape.blend",
        "..\\escape.blend",
        "/etc/passwd",
        "sub/nested.blend",
        "..",
        ".",
        ".hidden",
        "",
    ],
)
def test_illegal_file_names_are_refused(name: str) -> None:
    with pytest.raises(transfer.TransferError):
        transfer.FileManifest.from_dict(_entry(name=name))


def test_a_plain_file_name_is_accepted() -> None:
    entry = transfer.FileManifest.from_dict(_entry("scene.blend"))
    assert entry.name == "scene.blend"


def test_a_malformed_digest_is_refused() -> None:
    for digest in ("", "z" * 64, "abc"):
        with pytest.raises(transfer.TransferError, match="digest"):
            transfer.FileManifest.from_dict(_entry(digest=digest))


def test_an_absurd_size_is_refused() -> None:
    with pytest.raises(transfer.TransferError, match="out of range"):
        transfer.FileManifest.from_dict(_entry(size=transfer.MAX_FILE_BYTES + 1))


def test_a_correct_transfer_lands(tmp_path: Path) -> None:
    source = tmp_path / "src.bin"
    source.write_bytes(b"haze" * 5000)
    manifest = transfer.build_manifest([source])[0]

    dest = tmp_path / "dest"
    dest.mkdir()
    receiver = transfer.Receiver(manifest, dest)
    payload = source.read_bytes()
    for i in range(0, len(payload), 1024):
        receiver.write(payload[i : i + 1024])
    final = receiver.finish()

    assert final.read_bytes() == payload
    assert not (dest / "src.bin.part").exists(), "the .part file should be renamed away"


def test_a_corrupted_transfer_is_rejected_and_leaves_nothing(tmp_path: Path) -> None:
    """The point of per-chunk hashing: a corrupt input never becomes a job's
    input file, so a render cannot fail later for an unobvious reason."""
    source = tmp_path / "src.bin"
    source.write_bytes(b"original content here")
    manifest = transfer.build_manifest([source])[0]

    dest = tmp_path / "dest"
    dest.mkdir()
    receiver = transfer.Receiver(manifest, dest)
    receiver.write(b"tampered content here")  # same length, different bytes

    with pytest.raises(transfer.TransferError, match="checksum"):
        receiver.finish()
    assert list(dest.iterdir()) == [], "a failed transfer must leave no file behind"


def test_a_sender_cannot_exceed_its_declared_size(tmp_path: Path) -> None:
    source = tmp_path / "src.bin"
    source.write_bytes(b"small")
    manifest = transfer.build_manifest([source])[0]

    dest = tmp_path / "dest"
    dest.mkdir()
    receiver = transfer.Receiver(manifest, dest)
    with pytest.raises(transfer.TransferError, match="declared size"):
        receiver.write(b"x" * 10_000)
    assert list(dest.iterdir()) == []


def test_a_truncated_transfer_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "src.bin"
    source.write_bytes(b"abcdefghij")
    manifest = transfer.build_manifest([source])[0]

    dest = tmp_path / "dest"
    dest.mkdir()
    receiver = transfer.Receiver(manifest, dest)
    receiver.write(b"abcde")
    with pytest.raises(transfer.TransferError, match="expected"):
        receiver.finish()


def test_too_many_files_is_refused(tmp_path: Path) -> None:
    paths = []
    for i in range(transfer.MAX_FILES + 1):
        path = tmp_path / f"f{i}.bin"
        path.write_bytes(b"x")
        paths.append(path)
    with pytest.raises(transfer.TransferError, match="too many files"):
        transfer.build_manifest(paths)


def test_digests_are_stable_and_distinguishing(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"content")
    b.write_bytes(b"content")
    assert transfer.digest_of(a) == transfer.digest_of(b)
    b.write_bytes(b"different")
    assert transfer.digest_of(a) != transfer.digest_of(b)
