"""Mutual authentication over TLS.

Why this exists rather than plain TLS client certificates
---------------------------------------------------------
Python's ``ssl`` module cannot express "request a client certificate, hand it to
me, and let *me* decide" -- ``CERT_REQUIRED`` validates against a trust store
before the application sees anything, and ``CERT_NONE`` requests no certificate
at all. Cert-pinned mutual TLS would therefore mean rebuilding the SSLContext
and restarting the listener on every pairing change, and would still leave
pairing (where the peer is unknown by definition) needing a separate path.

So TLS runs with ``CERT_NONE`` in both directions and provides confidentiality,
integrity and forward secrecy, while authentication happens one layer up, in a
single code path shared by pairing and normal connections.

The relay attack, and what stops it
-----------------------------------
Application-layer authentication over an unauthenticated channel is normally
vulnerable to relaying: a machine-in-the-middle terminates both legs and passes
the challenge and response through untouched, authenticating itself as the
client without ever holding the client's key.

The defence is that **the client signs the server's public key**, not just a
nonce::

    sig = Sign(domain, server_pubkey || client_pubkey || nonce)

A relaying attacker must present its *own* key to the client (it has no other
way to terminate that leg), so the client signs the attacker's key. The real
server then checks the signature against the key it actually holds, finds the
wrong one, and refuses. The signature is bound to the specific TLS session it
was produced in.

For pairing, the SAS the user compares covers both public keys as well, so the
attack fails twice over -- once in code, once on the screen.
"""

from __future__ import annotations

import asyncio
import os
import platform as _platform
import ssl
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import haze
from haze import log
from haze.identity import certs
from haze.identity.keys import Identity, verify
from haze.identity.nodeid import from_public_key
from haze.transport import frames, tls

_log = log.get("transport.handshake")

AUTH_DOMAIN = b"haze-node-auth-v1"
NONCE_BYTES = 32
HANDSHAKE_TIMEOUT_S = 10.0


class HandshakeError(Exception):
    """The peer failed authentication. Always closes the connection."""


@dataclass(frozen=True)
class PeerIdentity:
    """An authenticated peer, as established by the handshake."""

    node_id: str
    public_key: bytes
    cert_der: bytes
    display_name: str
    platform: str
    agent_version: str
    node_port: int = 0
    """The port this peer *listens* on.

    Must come from the peer, not from the socket: the source port of an
    inbound connection is ephemeral, so a node that only ever receives
    connections would otherwise never learn how to call back.
    """


def _describe(identity: Identity, node_name: str, node_port: int) -> dict[str, object]:
    return {
        "node_id": identity.node_id,
        "name": node_name,
        "platform": f"{_platform.system()} {_platform.machine()}",
        "version": haze.__version__,
        "node_port": node_port,
        "cert_pem": certs.cert_path().read_text(),
    }


def _peer_from(payload: dict[str, object]) -> PeerIdentity:
    """Parse and validate the identity half of a handshake message.

    The node ID is *recomputed* from the certificate rather than trusted from
    the payload. A peer does not get to choose what it is called: claiming a
    node ID that does not hash from the key you are proving possession of is
    the whole attack this prevents.
    """
    pem = payload.get("cert_pem")
    if not isinstance(pem, str):
        raise HandshakeError("handshake message has no certificate")

    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
        public_key = certs.public_key_of(cert)
    except Exception as exc:
        raise HandshakeError(f"unusable peer certificate: {exc}") from exc

    derived = from_public_key(public_key)
    claimed = payload.get("node_id")
    if claimed != derived:
        raise HandshakeError(f"peer claims node id {claimed!r} but its key derives {derived!r}")

    return PeerIdentity(
        node_id=derived,
        public_key=public_key,
        cert_der=cert.public_bytes(serialization.Encoding.DER),
        display_name=str(payload.get("name") or "unnamed"),
        platform=str(payload.get("platform") or ""),
        agent_version=str(payload.get("version") or ""),
        node_port=_as_port(payload.get("node_port")),
    )


def _as_port(value: object) -> int:
    """Coerce a peer-supplied port. Anything out of range becomes 0, which
    callers read as "no usable callback address" -- a peer does not get to make
    us dial port 70000 or a negative number."""
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return value if 1 <= value <= 65535 else 0


def _signed_material(server_key: bytes, client_key: bytes, nonce: bytes) -> bytes:
    # Fixed-width fields, so no concatenation ambiguity is possible.
    return server_key + client_key + nonce


async def server_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    identity: Identity,
    node_name: str,
    node_port: int,
) -> PeerIdentity:
    """Server side. Returns the authenticated peer, or raises."""
    nonce = os.urandom(NONCE_BYTES)
    await frames.write_frame(
        writer, frames.message("hello", nonce=nonce.hex(), **_describe(identity, node_name, node_port))
    )

    message = await asyncio.wait_for(frames.read_frame(reader), HANDSHAKE_TIMEOUT_S)
    if message.get("type") != "auth":
        raise HandshakeError(f"expected 'auth', got {message.get('type')!r}")
    if message.get("v") != haze.PROTOCOL_VERSION:
        raise HandshakeError(
            f"peer speaks protocol v{message.get('v')}, this agent speaks "
            f"v{haze.PROTOCOL_VERSION}; upgrade the older node"
        )

    peer = _peer_from(message)

    signature = message.get("sig")
    if not isinstance(signature, str):
        raise HandshakeError("auth message carries no signature")

    # THE relay defence: the material includes *our* public key, so a signature
    # produced for a different server cannot be replayed at us.
    material = _signed_material(identity.public_key, peer.public_key, nonce)
    if not verify(peer.public_key, AUTH_DOMAIN, material, bytes.fromhex(signature)):
        raise HandshakeError(
            "signature does not verify against the peer's own key and this session -- "
            "either the peer does not hold its private key, or something is relaying "
            "this connection"
        )

    return peer


async def client_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    identity: Identity,
    node_name: str,
    node_port: int,
    ssl_object: ssl.SSLObject | None,
    expected_public_key: bytes | None = None,
) -> PeerIdentity:
    """Client side. Returns the authenticated peer, or raises.

    ``expected_public_key`` is the pin for an already-paired peer. When it is
    ``None`` (pairing), the peer's key is accepted here and authenticated by the
    user comparing the SAS instead.
    """
    message = await asyncio.wait_for(frames.read_frame(reader), HANDSHAKE_TIMEOUT_S)
    if message.get("type") != "hello":
        raise HandshakeError(f"expected 'hello', got {message.get('type')!r}")
    if message.get("v") != haze.PROTOCOL_VERSION:
        raise HandshakeError(
            f"peer speaks protocol v{message.get('v')}, this agent speaks "
            f"v{haze.PROTOCOL_VERSION}; upgrade the older node"
        )

    peer = _peer_from(message)

    # The certificate the peer described must be the one it actually terminated
    # TLS with. Without this, a peer could present its own certificate to
    # OpenSSL and describe somebody else's in the payload.
    presented = tls.peer_public_key(ssl_object)
    if not tls.key_matches(presented, peer.public_key):
        raise HandshakeError("the certificate in the hello is not the one used for this TLS session")

    if expected_public_key is not None and not tls.key_matches(presented, expected_public_key):
        raise HandshakeError(
            f"{peer.node_id.split('-')[0]} presented a different key than the one recorded "
            f"when you paired with it. Refusing to connect."
        )

    nonce_hex = message.get("nonce")
    if not isinstance(nonce_hex, str):
        raise HandshakeError("hello carries no nonce")

    material = _signed_material(peer.public_key, identity.public_key, bytes.fromhex(nonce_hex))
    await frames.write_frame(
        writer,
        frames.message(
            "auth",
            sig=identity.sign(AUTH_DOMAIN, material).hex(),
            **_describe(identity, node_name, node_port),
        ),
    )
    return peer
