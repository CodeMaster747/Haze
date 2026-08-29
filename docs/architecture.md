# Haze — Architecture

How the pieces fit, and why each one is shaped the way it is. The decisions
below were mostly forced by a constraint rather than chosen freely, and the
constraint is more interesting than the choice.

---

## The shape of it

```
   ┌─ your browser ──────────────────────────────────────┐
   │  http://127.0.0.1:7433   ← one origin, always       │
   └───────────────┬─────────────────────────────────────┘
                   │  same-origin REST + WebSocket
   ┌───────────────▼─────────────── node A (hub) ────────┐
   │  FastAPI + uvicorn, bound to the 127.0.0.1 literal  │
   │    GET /   → the bundled React dashboard            │
   │    /api/v1 → REST     /ws → telemetry, pairing,     │
   │                              discovery, jobs        │
   │  ─────────────────────────────────────────────────  │
   │  scheduler (pure)   probe    executor    blobs      │
   │  discovery          pairing  identity    SQLite     │
   └───────────────┬─────────────────────────────────────┘
                   │  TLS 1.3, mutual auth, :8443
                   │  raw asyncio — NOT uvicorn
   ┌───────────────▼──────────┐   ┌──────────────────────┐
   │  node B (desktop / GPU)  │   │  node C (NAS)        │
   └──────────────────────────┘   └──────────────────────┘
```

Two servers in one process, deliberately:

- **uvicorn on loopback** serves the dashboard and its API. There is no client
  certificate here, so uvicorn's limitations do not bite.
- **raw asyncio on `:8443`** serves other nodes. It has to be raw, because
  uvicorn does not expose the peer certificate to the ASGI app (FastAPI
  discussions #7176, #8395) — and the peer certificate *is* a node's identity.

---

## Why the dashboard is served by the agent

This is the load-bearing decision, and it was forced.

The obvious design — host the dashboard, have it call `http://127.0.0.1:7433` —
is dead in 2026:

| Browser | Behaviour |
|---|---|
| Safari | Blocks HTTPS → `http://127.0.0.1` as mixed content. No override. [WebKit #171934](https://bugs.webkit.org/show_bug.cgi?id=171934), open since 2017 |
| Chrome 142+ | Local Network Access permission prompt for any public-origin request to loopback |
| Chrome 147+ | Extended that gate to WebSockets, closing the last workaround |

Same-address-space requests are exempt. So the SPA is built into the Python
wheel and served by the agent itself: loopback → loopback. That single choice
removes CORS, mixed content, the permission prompt, and certificate warnings at
once. Syncthing (`:8384`), Jellyfin (`:8096`), Home Assistant (`:8123`) and
Ollama (`:11434`) all arrived at the same place.

**Multi-node inherits the exemption for free.** The agent you open is the hub;
it proxies to other nodes over the agent-to-agent transport. The browser never
addresses `192.168.x.x`, so an N-node permission problem collapses into a
one-origin problem.

---

## Identity and trust

A node *is* an Ed25519 keypair. Everything derives from it.

The node ID is `SHA-256(raw public key)` in Luhn-checked base32 groups —
diverging from Syncthing, which hashes the certificate, so that a certificate
can be regenerated without the node becoming a stranger to its peers.

**Pairing** shows six digits derived *from both public keys*. There is no
secret to guess. A machine-in-the-middle must substitute a key on at least one
leg, so the two screens disagree. Both users must confirm.

**The handshake** is where the interesting constraint lives. Python's `ssl`
cannot express "request a client certificate, hand it to me, and let *me*
decide" — `CERT_REQUIRED` validates before the app sees anything, `CERT_NONE`
requests nothing. So TLS provides confidentiality and forward secrecy, and
authentication happens one layer up:

```
server → client   hello  { node_id, cert, nonce }
client → server   auth   { node_id, cert, sig }

sig = Ed25519(server_pubkey ‖ client_pubkey ‖ nonce)
```

**The client signs the server's public key.** That is what defeats a relay: an
attacker terminating both legs must show the client its own key, so the real
server checks the signature against the key it holds, finds the wrong one, and
refuses. The signature is bound to the TLS session that produced it.

See [SECURITY.md](../SECURITY.md) for the full model, including what Haze does
*not* defend against.

---

## Discovery

Three mechanisms run together, not as a fallback chain — they fail in
uncorrelated ways, so the union finds more and the *difference* is diagnostic.

| | Finds | Fails when |
|---|---|---|
| mDNS (`_haze._tcp`) | across the subnet | multicast filtered — mesh APs with IGMP snooping, `avahi-daemon` holding UDP 5353 |
| UDP broadcast | the local segment | broadcast blocked, or peer on another subnet |
| By address | anything routable | never |

**Keyed on node ID, never address.** `haze devnet` runs four agents behind one
IP; an address-keyed registry would silently collapse them into one node.

One case no mechanism can fix: an access point isolating clients from each
other. Haze detects it — the node advertises but no connection opens — and says
so, rather than reporting a timeout that sends you hunting in the wrong place.

---

## Jobs

An **allowlist**, not a shell. A job names a runtime (`hashbench`, `blender`,
`ffmpeg`) and supplies typed arguments; the runtime builds the argv. No shell
anywhere, and no peer-controlled field becomes a command name. Paths resolve
strictly inside the job's own directory.

That is narrower than "run this command remotely" and much easier to defend:
the alternative makes every paired node a remote shell.

**Resource caps report what they actually are.** Linux gets cgroups v2 via
`systemd-run`: real kernel enforcement. macOS has no equivalent — `RLIMIT_AS`
bounds address space rather than resident set, and CPU share is not enforceable
at all. The UI says which you got. A cap that silently is not enforced is worse
than no cap, because it makes someone comfortable running a job they should
have thought harder about.

Wall clock *is* enforced everywhere, by Haze itself, killing the process
**group** — ffmpeg and Blender both spawn helpers that outlive their parent.

---

## The scheduler

A pure function: no clock, no randomness, no I/O. It ranks by **predicted
end-to-end time** — compute plus moving the bytes — rather than by a weighted
average of niceness.

That ranking is not cosmetic. An earlier version scored normalised dimensions
and normalised `transfer` *against the other candidates*, so the cheapest remote
node always scored 1.0 on it. With one remote node the dimension could never
penalise anything, and the scheduler chose an 18-second round trip over a
10-second local run — precisely the decision it existed to prevent.

Purity is what makes the browser demo honest. `pytest` writes a golden corpus
of `(cluster, job) → decision` records; a vitest suite replays it against the
TypeScript implementation the demo runs. Change one and CI fails until you
change the other.

It caught two real divergences immediately, neither findable by testing either
side alone:

1. Python renders `10.0` as `"10.0"`, JavaScript as `"10"`.
2. The fix for (1) was also wrong — Python's `f"{v:.2f}"` rounds half to even,
   JS `toFixed` rounds half away from zero, so `0.125` differed. Both now round
   with the same floor expression and build the string from integers.

---

## What is deliberately absent

- **Interactive application streaming.** It is a product, not a feature. The
  leading open-source implementation is ~2.5 MB of C++ built by an organisation
  since 2020, its macOS support is experimental with broken input on Apple
  Silicon, and WAN streaming cannot be free because 10–30% of connections fall
  back to a bandwidth-metered TURN relay. What ships instead is live job
  telemetry and outputs appearing as the remote machine produces them.
- **A cloud backend.** There is nothing to deploy but a static page. That is
  what makes the zero-cost claim structural rather than hopeful.
- **Arbitrary remote execution.** See the allowlist above.
- **Alembic.** One local SQLite schema per agent; delete the file and re-pair.
