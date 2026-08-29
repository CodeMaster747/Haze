"""Self-signed TLS certificates for node-to-node connections.

The certificate is a *container* for the identity public key, not a source of
trust. Nothing validates a chain to decide whether a peer is legitimate: after
the handshake, both sides compare the peer's raw Ed25519 public key against the
one recorded at pairing time. Syncthing makes the same call — in its words, the
self-signing "doesn't add any security or functionality... but it enables the
use of the keys in a standard TLS exchange".

Key reuse
---------
The same Ed25519 key signs this certificate and (later) capability grants.
That is cross-protocol key reuse, which is normally a smell. It is safe here
because the two message spaces are disjoint by construction: TLS 1.3
CertificateVerify signs a transcript prefixed with 64 space bytes and the fixed
ASCII string "TLS 1.3, server CertificateVerify", while everything Haze signs
goes through Identity.sign(), which prepends a length-delimited domain string.
No message in one space can be reinterpreted as a message in the other.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

from haze import config, log
from haze.identity.keys import Identity

_log = log.get("identity.certs")

CERT_FILENAME = "node.crt"

# Ten years. Certificate rotation is an operations burden, and this certificate
# carries no authority a shorter lifetime would limit -- it is pinned by public
# key, and revocation is "remove the peer", not "wait for expiry".
_LIFETIME = dt.timedelta(days=3653)


def cert_path() -> Path:
    return config.state_dir() / CERT_FILENAME


def key_pem_path() -> Path:
    """PEM copy of the private key.

    Python's ssl module can only load a certificate chain from files on disk --
    there is no API to hand it an in-memory key. So the seed in identity.key is
    the source of truth and this is a derived 0600 artifact, regenerated
    whenever the certificate is.
    """
    return config.state_dir() / "node.key.pem"


def load_or_create(identity: Identity) -> x509.Certificate:
    """Return this node's certificate, generating it if absent or stale."""
    path = cert_path()

    if path.exists() and key_pem_path().exists():
        cert = x509.load_pem_x509_certificate(path.read_bytes())
        if _matches(cert, identity) and not _expired(cert):
            return cert
        # The identity key changed, or the certificate aged out. Either way the
        # certificate no longer represents this node; regenerate. The node ID is
        # unaffected because it is derived from the key, not the certificate.
        _log.info("regenerating node certificate (stale or key mismatch)")

    cert = _generate(identity)
    _write(cert, identity)
    return cert


def _generate(identity: Identity) -> x509.Certificate:
    now = dt.datetime.now(dt.UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "haze")])

    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(identity.private_key.public_key())
        .serial_number(x509.random_serial_number())
        # Backdated a day so a peer whose clock is slightly behind does not
        # reject a certificate generated moments ago. NAS boxes without an RTC
        # make this a real case, not a theoretical one.
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + _LIFETIME)
        # A self-signed leaf is more reliably accepted as its own trust anchor
        # across OpenSSL builds when it is marked as a CA. Defence in depth
        # only: the authoritative check is the public-key comparison.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        # Nodes are addressed by ID, not by DNS name, and hostname checking is
        # off. This SAN exists so a human running `openssl x509 -text` can see
        # which node they are looking at.
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.UniformResourceIdentifier(f"haze://{identity.node_id}")]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(identity.private_key.public_key()),
            critical=False,
        )
        # algorithm=None is required for Ed25519: the curve fixes the hash, so
        # passing one is an error rather than a choice.
        .sign(identity.private_key, algorithm=None)
    )


def _write(cert: x509.Certificate, identity: Identity) -> None:
    config.ensure_state_dir()
    cert_path().write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    pem = identity.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = key_pem_path()
    tmp = path.with_suffix(".pem.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    _log.debug("wrote %s and %s", cert_path(), path)


def _matches(cert: x509.Certificate, identity: Identity) -> bool:
    return public_key_of(cert) == identity.public_key


def _expired(cert: x509.Certificate) -> bool:
    return cert.not_valid_after_utc <= dt.datetime.now(dt.UTC)


def public_key_of(cert: x509.Certificate) -> bytes:
    """Raw 32-byte Ed25519 public key from a certificate.

    Raises if the certificate holds any other key type. A peer presenting an RSA
    or ECDSA certificate is not a Haze node, and treating it as one would mean
    comparing a pinned Ed25519 key against something that can never equal it --
    a confusing failure much later instead of a clear one here.
    """
    key = cert.public_key()
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError(f"expected an Ed25519 certificate, got {type(key).__name__}")
    return key.public_bytes_raw()


def fingerprint(cert: x509.Certificate) -> str:
    """SHA-256 of the DER certificate, hex. For display and logs only —
    identity comparisons use the raw public key, which survives certificate
    regeneration."""
    return cert.fingerprint(hashes.SHA256()).hex()
