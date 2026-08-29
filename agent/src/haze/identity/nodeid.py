"""Node identifiers.

A node's identity is its Ed25519 public key. The node ID is a human-readable
encoding of that key's SHA-256, following Syncthing's device-ID format closely
enough that the reasoning behind it carries over.

Deliberate divergence from Syncthing: Syncthing hashes the DER *certificate*,
so rotating the certificate changes the device ID forever. Haze hashes the raw
32-byte *public key*, so the TLS certificate can be regenerated (on expiry, or
to change a field) without the node becoming a stranger to its peers.

Format
------
    SHA-256(raw pubkey)          32 bytes
    base32, padding stripped     52 chars
    split into 4 groups of 13
    append a Luhn check char     56 chars
    regroup into 8 groups of 7   "K7QXM3V-BONSGYC-..."

The Luhn check characters are the point of the whole exercise: a user reads a
node ID aloud or retypes it off another screen when confirming a pairing, and a
single transposed character has to be caught there rather than silently
comparing two different nodes.
"""

from __future__ import annotations

import base64
import hashlib

# RFC 4648 base32. Excludes 0, 1, 8, 9 — which is why it survives being read
# aloud or copied by hand better than hex does.
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

_GROUP = 13
_GROUPS = 4
_DISPLAY_GROUP = 7
_GROUP_TOTAL = _GROUPS * (_GROUP + 1)  # 56


def luhn_check_char(chunk: str) -> str:
    """Luhn mod-N check character over :data:`ALPHABET`.

    Same construction as Syncthing's ``luhn.go``. Catches every single-character
    substitution and every adjacent transposition, which are the two mistakes a
    human actually makes when copying one of these.
    """
    n = len(ALPHABET)
    factor = 1
    total = 0
    for ch in chunk:
        codepoint = ALPHABET.find(ch)
        if codepoint == -1:
            raise ValueError(f"character {ch!r} is not in the base32 alphabet")
        addend = factor * codepoint
        factor = 1 if factor == 2 else 2
        total += (addend // n) + (addend % n)
    return ALPHABET[(n - (total % n)) % n]


def from_public_key(public_key: bytes) -> str:
    """Canonical node ID for a raw 32-byte Ed25519 public key."""
    if len(public_key) != 32:
        raise ValueError(f"expected a 32-byte Ed25519 public key, got {len(public_key)}")

    digest = hashlib.sha256(public_key).digest()
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=")

    checked = "".join(
        chunk + luhn_check_char(chunk)
        for chunk in (encoded[i * _GROUP : (i + 1) * _GROUP] for i in range(_GROUPS))
    )
    return "-".join(
        checked[i : i + _DISPLAY_GROUP] for i in range(0, len(checked), _DISPLAY_GROUP)
    )


def normalise(node_id: str) -> str:
    """Accept the sloppy forms a human produces, return the canonical one.

    Handles lowercase, missing or extra dashes, spaces, and the classic
    homoglyph substitutions (0 for O, 1 for I) that base32's alphabet invites.
    """
    cleaned = (
        node_id.strip()
        .upper()
        .replace("-", "")
        .replace(" ", "")
        .replace("0", "O")
        .replace("1", "I")
        .replace("8", "B")
    )
    if len(cleaned) != _GROUP_TOTAL:
        raise ValueError(f"node id must be {_GROUP_TOTAL} characters, got {len(cleaned)}")
    return "-".join(
        cleaned[i : i + _DISPLAY_GROUP] for i in range(0, len(cleaned), _DISPLAY_GROUP)
    )


def is_valid(node_id: str) -> bool:
    """True if every group's Luhn check character verifies."""
    try:
        cleaned = normalise(node_id).replace("-", "")
    except ValueError:
        return False
    for i in range(_GROUPS):
        group = cleaned[i * (_GROUP + 1) : (i + 1) * (_GROUP + 1)]
        try:
            if luhn_check_char(group[:_GROUP]) != group[_GROUP]:
                return False
        except ValueError:
            return False
    return True


def short(node_id: str) -> str:
    """First display group, for logs and dense UI.

    7 base32 characters is 35 bits. Enough to tell your three machines apart at
    a glance; NEVER enough to authenticate with. Every security decision uses
    the full ID or the raw key.
    """
    return node_id.split("-")[0]
