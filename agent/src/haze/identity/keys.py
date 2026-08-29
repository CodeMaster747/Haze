"""This node's long-lived Ed25519 identity.

One keypair per node, generated on first run, never rotated. Everything else
derives from it: the node ID, the TLS certificate, and the signature that proves
to a peer that we are who our node ID says.

Storage decision
----------------
The key is stored as a 0600 file, not in the OS keychain, and that is a
deliberate choice rather than a shortcut.

macOS Keychain ACLs bind to the *calling binary's path*. `haze up` is a
long-running background process, so the moment the venv is rebuilt or Homebrew
ships a Python point release, the Keychain either re-prompts or fails outright
— and there is no interactive session to answer the prompt. On headless Linux
(the NAS, the single most likely Haze node) `keyring` reports the SecretService
backend as available and then fails at runtime because there is no D-Bus
session.

A 0600 file in a 0700 directory protects the key from other local users, which
is the same threat the keychain defends against here. It does not protect
against the logged-in user or root — and neither does the keychain. On macOS
the file additionally sits inside FileVault's encrypted volume at rest.

See docs/SECURITY.md. Keychain integration is a reasonable future addition for
the interactive CLI path; it is the wrong default for the daemon.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

from haze import config, log
from haze.identity import nodeid

_log = log.get("identity")

KEY_FILENAME = "identity.key"


@dataclass(frozen=True)
class Identity:
    """This node's keypair and the names derived from it."""

    private_key: ed25519.Ed25519PrivateKey
    public_key: bytes
    """Raw 32 bytes. This, not the certificate, is what peers pin."""
    node_id: str

    @property
    def short_id(self) -> str:
        return nodeid.short(self.node_id)

    def sign(self, domain: bytes, message: bytes) -> bytes:
        """Sign with an explicit domain-separation prefix.

        Every signature this key produces outside TLS goes through here, so no
        two protocols can ever be induced to accept each other's signatures.
        The prefix is length-delimited rather than concatenated: without the
        length byte, ``(b"ab", b"c")`` and ``(b"a", b"bc")`` would sign
        identical bytes.
        """
        if len(domain) > 255:
            raise ValueError("domain separator too long")
        return self.private_key.sign(bytes([len(domain)]) + domain + message)


def verify(public_key: bytes, domain: bytes, message: bytes, signature: bytes) -> bool:
    """Counterpart to :meth:`Identity.sign`. Never raises."""
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, bytes([len(domain)]) + domain + message
        )
    except Exception:
        return False
    return True


def key_path() -> Path:
    return config.state_dir() / KEY_FILENAME


def load_or_create() -> Identity:
    """Load this node's identity, generating it on first run."""
    path = key_path()
    if path.exists():
        seed = _read_key(path)
        _log.debug("loaded identity from %s", path)
    else:
        config.ensure_state_dir()
        private = ed25519.Ed25519PrivateKey.generate()
        seed = private.private_bytes_raw()
        _write_key(path, seed)
        _log.info("generated a new node identity at %s", path)

    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key().public_bytes_raw()
    return Identity(
        private_key=private_key,
        public_key=public_key,
        node_id=nodeid.from_public_key(public_key),
    )


def _write_key(path: Path, seed: bytes) -> None:
    """Write the 32-byte seed at 0600, atomically.

    O_EXCL on a temporary file then os.replace, rather than open(path, "wb"):
    the key must never exist on disk with default permissions, not even for the
    instant between creation and chmod.
    """
    tmp = path.with_suffix(".key.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(seed)
            fh.flush()
            # The identity is the one piece of state that must survive a power
            # cut: losing it means every peer has to re-pair.
            os.fsync(fh.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def _read_key(path: Path) -> bytes:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        # Refuse rather than repair. A group- or world-readable private key
        # should be treated as compromised, and silently chmod-ing it would
        # hide that fact from the only person who can act on it.
        raise PermissionError(
            f"{path} is mode {mode:04o}; a private key must not be readable by group or others.\n"
            f"If this key may have been exposed, delete it and re-pair every peer:\n"
            f"    rm {path}"
        )
    seed = path.read_bytes()
    if len(seed) != 32:
        raise ValueError(
            f"{path} is {len(seed)} bytes; an Ed25519 seed is 32. The file is corrupt — "
            f"delete it and re-pair every peer."
        )
    return seed
