# Haze — Security Model

Haze lets one of your machines run processes on another. That is a serious
capability, so this document states plainly what the design defends against,
what it does not, and where the honest limits are.

Nothing here is aspirational. Every claim in [What Haze defends
against](#what-haze-defends-against) has a test in
`agent/tests/test_pairing_integration.py`.

---

## Identity

Every node generates one Ed25519 keypair on first run and never rotates it.
Everything else derives from that key:

- **Node ID** — `SHA-256(raw public key)`, base32, in groups with Luhn check
  characters: `A2JBP7T-MNA7I2R-…`. The check characters catch single-character
  substitutions and adjacent transpositions, because a human reads these aloud
  or retypes them off another screen.
- **TLS certificate** — self-signed with the same key. It is a *container* for
  the public key, not a source of trust; nothing validates a chain to decide
  whether a peer is legitimate.

Hashing the public key rather than the certificate (Syncthing hashes the
certificate) means the certificate can be regenerated on expiry without the node
becoming a stranger to every peer.

**Key storage is a 0600 file, not the OS keychain.** This is a deliberate
choice. macOS Keychain ACLs bind to the calling binary's path, so a long-running
`haze up` breaks the first time the venv is rebuilt or Homebrew ships a Python
point release — with no interactive session to answer the re-prompt. On headless
Linux (a NAS, the most likely Haze node) `keyring` reports the SecretService
backend as available and then fails at runtime with no D-Bus session. A 0600
file in a 0700 directory defends against other local users, which is the same
threat the keychain addresses here. The agent **refuses to start** if the
permissions are looser, rather than silently repairing them — a world-readable
private key should be treated as compromised, and quietly fixing it would hide
that from the only person who can act.

That check is POSIX-only. Windows has no mode bits — `os.stat` reports 0666 for
every file and `os.chmod` only toggles the read-only flag — so the check is
skipped there rather than being made to fail on every file. On Windows the
equivalent protection is the ACL on the user's profile directory, which
`%USERPROFILE%\.haze` inherits: other non-administrator users cannot read it.
Administrators and SYSTEM can, which is the same caveat root carries on Unix.

## Pairing

Two nodes establish trust by showing the same six digits on both screens.

```
   workstation                                    laptop
   ───────────                                    ──────
   arms pairing  ──────── 3 minute window ────►
                          ◄──── TLS 1.3 ─────    connects
                          ◄──── identity ────►

        385664                                    385664
   buzzard talon                              buzzard talon
  dragnet aardvark                           dragnet aardvark

   user confirms                              user confirms
                    ─── both, or nothing ───
```

The code is an **output** of both public keys, not an input:

```
SAS = HKDF-SHA256(sorted(pubkey_a ‖ pubkey_b), info="haze-sas-v1")[:4]  → 6 digits
```

There is no secret to guess and nothing to brute-force. A machine-in-the-middle
must terminate TLS on both legs, which means substituting its own public key on
at least one — so the two screens compute different values and disagree. This is
the Signal safety-number / SSH fingerprint model.

Four things make it hold in practice:

1. **Both users must confirm.** Confirming on one side pairs nobody. Without
   this, a device on your network could pair itself while you were in another room.
2. **Pairing must be armed explicitly**, and closes after 3 minutes or on the
   first success. An always-pairable node is one any device on the LAN can knock on.
3. **The words are shown alongside the digits.** `buzzard talon dragnet
   aardvark` is much harder to misread as matching than `385664`.
4. **Confirm is not the default button.** A dialog that is easy to click through
   is security theatre; the mechanism rests on the user actually looking at the
   other screen.

## Transport

TLS 1.3 only, both directions, with authentication one layer above it.

Python's `ssl` module cannot express "request a client certificate, hand it to
me, and let *me* decide" — `CERT_REQUIRED` validates against a trust store
before the application sees anything, and `CERT_NONE` requests no certificate at
all. Cert-pinned mutual TLS would therefore mean rebuilding the `SSLContext` and
restarting the listener on every pairing change, and would still need a separate
path for pairing, where the peer is unknown by definition.

So TLS provides confidentiality, integrity and forward secrecy, and
authentication is a challenge-response in one code path shared by both cases:

```
server → client   hello  { node_id, cert, nonce }
client → server   auth   { node_id, cert, sig }

sig = Ed25519(server_pubkey ‖ client_pubkey ‖ nonce)
```

**The client signs the server's public key.** That is what defeats a relay
attack: an attacker terminating both legs must present its *own* key to the
client, so the client signs the attacker's key, and the real server checks the
signature against the key it actually holds, finds the wrong one, and refuses.
The signature is bound to the specific TLS session that produced it.

The client additionally pins the server's key for any already-paired peer, and
verifies that the certificate described in the `hello` is the one that actually
terminated the TLS session.

A peer's **node ID is recomputed from its certificate**, never trusted from the
payload — a peer does not get to choose what it is called.

## Revocation

`haze unpair` deletes the row. The peer leaves the trust set and its next
connection is refused at the handshake. There is no revocation list, no expiry
to wait out, and no online service to reach.

## The loopback API

The dashboard API can start processes, so it is authenticated even though it
listens only on `127.0.0.1`. Two independent gates:

- **Bearer token** from a 0600 file, compared with `hmac.compare_digest`.
- **Origin allowlist**, enforced on `/api` calls *and* on the WebSocket upgrade.

The second is not optional. **WebSocket upgrades carry no CORS preflight**, and
Firefox currently lets any HTTPS page open `ws://127.0.0.1` with no prompt at
all. Without the Origin check, any website you visit in another tab could
enumerate and drive your cluster. This is the "Local Mess" bug class that
motivated Chrome's Local Network Access work, and it is why these are tests
rather than hardening notes.

Also: bound to the `127.0.0.1` literal (never `0.0.0.0`, never the name
`localhost`, which can resolve to `::1` first on macOS); no
`Access-Control-Allow-Origin` header is emitted anywhere; `X-Frame-Options:
DENY`; interactive API docs disabled.

---

## What Haze defends against

| Threat | Mechanism |
|---|---|
| A hostile device on your WiFi joining your cluster | Pairing must be armed, and both users must confirm matching codes |
| A machine-in-the-middle during pairing | It must substitute a key, so the two screens disagree |
| A relay attack on the handshake | The client signs the server's public key, binding the signature to that session |
| A peer impersonating another node | The node ID is recomputed from the certificate, not read from the payload |
| A paired node being replaced by a different machine | The public key is pinned; a mismatch is refused with a plain-language error |
| Passive eavesdropping, a hostile router, your ISP | TLS 1.3, AEAD, forward secrecy via ephemeral X25519 |
| A web page you visit driving your cluster | Bearer token plus an Origin allowlist on both HTTP and the WebSocket upgrade |
| A revoked peer reconnecting | Unpairing removes it from the trust set; the handshake refuses it |
| Another local user reading your identity key | 0600 in a 0700 directory; the agent refuses to start if that is loosened (on Windows, the profile directory's ACL) |

## What Haze does *not* defend against

Stated as plainly as the list above, because a security document that only
lists wins is not useful.

- **A fully compromised paired node.** It holds a valid key and can do
  everything you permitted it to. The mitigation is `haze unpair`, not prevention.
- **Physical access, or root, on any node.** File permissions protect the key
  from *other local users*. They do not protect it from you, from root, or from
  a debugger attached to the running agent. Neither would a keychain.
- **Hostile code inside a job.** Haze v1 uses OS process limits, not a
  hypervisor or a hardened container runtime. **Haze is not a
  hostile-multi-tenant sandbox. Only run jobs from machines you own.**
- **Resource caps on macOS.** cgroups v2 (Linux) and Job Objects (Windows) can
  genuinely bound CPU and memory. macOS has no equivalent — `setrlimit` and
  `nice` are what exist, and the caps there are advisory. The UI will say so
  rather than implying enforcement that is not happening.
- **Denial of service**, from a paired peer or anything that can reach the port.
- **Traffic analysis.** Packet sizes and timing leak job size and activity.
- **Supply-chain compromise of dependencies.** Reduced by a small dependency
  tree and pinned versions; not eliminated.
- **Post-quantum adversaries.** X25519 and Ed25519 are not PQ-secure.
- **A shoulder-surfed pairing code** — *partially*. The window is 3 minutes,
  single-use, and both machines display the peer's node ID afterwards, so an
  unexpected device is visible.

## Reporting

This is a personal project, not a product. If you find something, open an issue
at <https://github.com/CodeMaster747/Haze/issues>.
