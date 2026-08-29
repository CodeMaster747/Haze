"""TLS 1.3 contexts for node-to-node connections.

Trust model
-----------
Certificates are pinned, not chained. A peer is legitimate if and only if the
raw Ed25519 public key in the certificate it presents is one we recorded when
the user paired with it. There is no CA, no Let's Encrypt, no internet
dependency, and pairing works on an aeroplane.

Chain validation against a bundle of paired certificates runs as well, as
defence in depth -- but :func:`peer_public_key` is the authoritative check, and
it is run explicitly on both sides after every handshake. That ordering is
deliberate: if some OpenSSL build validated a chain more loosely than expected,
it must not be able to turn into an authentication bypass.

Why this does not run on uvicorn
--------------------------------
Uvicorn does not expose the peer certificate to the ASGI application (a
long-standing FastAPI limitation, discussions #7176 / #8395). Since the peer
certificate *is* a node's identity, node-to-node RPC needs a raw asyncio TLS
server. FastAPI keeps the loopback dashboard API, where there is no client
certificate to inspect.
"""

from __future__ import annotations

import hmac
import ssl
from collections.abc import Iterable

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from haze import log
from haze.identity import certs

_log = log.get("transport.tls")


def _base(purpose: ssl.Purpose) -> ssl.SSLContext:
    ctx = ssl.SSLContext(
        ssl.PROTOCOL_TLS_SERVER if purpose is ssl.Purpose.CLIENT_AUTH else ssl.PROTOCOL_TLS_CLIENT
    )
    # TLS 1.3 only. Nothing here has to interoperate with anything but another
    # Haze agent, so there is no reason to carry 1.2's cipher negotiation and
    # its downgrade surface.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    # Nodes are addressed by ID and often by bare IP; there is no DNS name to
    # check, and the public-key pin is strictly stronger than a name would be.
    ctx.check_hostname = False
    return ctx


def _load_identity(ctx: ssl.SSLContext) -> None:
    ctx.load_cert_chain(certfile=str(certs.cert_path()), keyfile=str(certs.key_pem_path()))


def _bundle(peer_certs: Iterable[bytes]) -> str:
    """PEM bundle from DER certificates."""
    return "".join(
        x509.load_der_x509_certificate(der)
        .public_bytes(serialization.Encoding.PEM)
        .decode("ascii")
        for der in peer_certs
    )


def server_context(peer_certs: Iterable[bytes]) -> ssl.SSLContext:
    """Listener context for connections from already-paired peers.

    Requires a client certificate that chains to one of the paired
    certificates, so an unpaired machine on the LAN is rejected during the
    handshake and never reaches any application code.
    """
    ctx = _base(ssl.Purpose.CLIENT_AUTH)
    _load_identity(ctx)

    bundle = _bundle(peer_certs)
    if not bundle:
        # With no paired peers there is nothing that could pass verification.
        # Requesting a certificate we can never accept would produce a
        # confusing handshake error, so say so plainly at the call site.
        raise NoPairedPeersError("no paired peers; nothing could authenticate")

    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cadata=bundle)
    return ctx


def pairing_server_context() -> ssl.SSLContext:
    """Listener context used *only* while the user has armed pairing.

    Requests no client certificate: the initiator is unknown by definition, so
    there is nothing to verify against. Confidentiality comes from TLS;
    authentication comes from the user comparing the SAS on both screens, and
    from the Ed25519 signature the initiator sends in-band.
    """
    ctx = _base(ssl.Purpose.CLIENT_AUTH)
    _load_identity(ctx)
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def client_context(expected_cert: bytes | None = None) -> ssl.SSLContext:
    """Dialling context.

    ``expected_cert`` is the DER certificate recorded for this peer at pairing
    time; pass ``None`` when pairing, where the peer is not yet known.

    Either way the client always sends its own certificate, and always verifies
    the peer by public key after the handshake.
    """
    ctx = _base(ssl.Purpose.SERVER_AUTH)
    _load_identity(ctx)

    if expected_cert is None:
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=_bundle([expected_cert]))
    return ctx


class NoPairedPeersError(RuntimeError):
    """Raised when a listener is asked for before any peer exists."""


def peer_public_key(ssl_object: ssl.SSLObject | None) -> bytes:
    """The authoritative identity check.

    Pulls the peer's raw Ed25519 public key straight off the completed
    handshake. Everything that decides whether a connection is trusted compares
    against this value.
    """
    if ssl_object is None:
        raise ValueError("connection is not TLS")
    der = ssl_object.getpeercert(binary_form=True)
    if not der:
        raise ValueError("peer presented no certificate")
    return certs.public_key_of(x509.load_der_x509_certificate(der))


def peer_cert_der(ssl_object: ssl.SSLObject | None) -> bytes:
    if ssl_object is None:
        raise ValueError("connection is not TLS")
    der = ssl_object.getpeercert(binary_form=True)
    if not der:
        raise ValueError("peer presented no certificate")
    return der


def key_matches(a: bytes, b: bytes) -> bool:
    """Constant-time public-key comparison.

    Public keys are not secret, so this is not defending against a timing
    oracle. It is here so that the one comparison the whole trust model rests
    on is visibly the careful kind, and nobody later swaps in ``==`` on a
    value that *is* sensitive.
    """
    return hmac.compare_digest(a, b)
