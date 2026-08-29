# Haze

**Pool your own machines into a private compute network.**

You probably own more than one computer: a laptop with a good screen and a weak
GPU, a desktop that is fast but sits idle, maybe a box with a lot of disk. Haze
makes them work as one personal cluster — submit a job from the laptop, run it
on the desktop's GPU, get the result back — with per-node limits you set.

No cloud provider, no account, no bill. You own every node.

> **Status: early.** Milestones 0–1 of 6 are complete — the agent, the loopback
> dashboard, live telemetry, and device pairing over mutually-authenticated
> TLS 1.3. Discovery, jobs and the scheduler are next. See
> [Roadmap](#roadmap) for exactly what works today.

---

## Why not just use a remote desktop / cloud VM / Syncthing?

Haze is none of those, and it is deliberately narrower than all of them:

|  | What it does | What Haze does instead |
|---|---|---|
| Remote desktop | Mirrors one machine's screen | Moves *work*, not pixels |
| Cloud VM | Rents someone else's hardware, monthly | Uses hardware you already own, free |
| Syncthing | Replicates files everywhere | Moves only what a job needs, then returns the result |

The honest framing: **Haze distributes workloads, it does not merge machines.**
Two computers do not become one computer with the sum of their cores. What Haze
does is decide *where* a piece of work should run and move it there.

## Install

```bash
uv tool install haze-agent     # or: pipx install haze-agent
haze up
```

The distribution is `haze-agent`; the command is `haze`. There is no installer
binary to download, on purpose — an unsigned binary triggers a malware warning
on macOS and Windows, and "this might be malware" is the wrong first impression
for a tool whose whole premise is running code on your machines. Code signing
costs $99/yr, which would break the zero-cost rule.

## Pair two machines

```bash
# on the first machine
haze up
haze pair --serve

# on the second
haze up
haze pair --host 192.168.1.42
```

Both screens show the same six digits and four words. Confirm on **both** —
that comparison is the entire security model, and neither side can pair alone.

```
        385664                      385664
   buzzard talon               buzzard talon
  dragnet aardvark            dragnet aardvark
```

The code is derived *from* the two machines' public keys, so there is nothing to
guess. A machine-in-the-middle would have to substitute a key, which makes the
two screens disagree. See [SECURITY.md](SECURITY.md).

## Try it on one machine

```bash
haze devnet up -n 4 --open
```

Starts four agents with synthetic hardware profiles — a fake workstation with an
RTX 4090, a NAS, and so on — so you can see the whole system work without owning
four computers. **Every simulated node is badged as such**, in the UI, in CLI
output and in screenshots. See [Simulated vs real](#simulated-vs-real).

## Architecture

```
   ┌─ your browser ──────────────────────────────────────┐
   │  http://127.0.0.1:7433   ← one origin, always       │
   └───────────────┬─────────────────────────────────────┘
                   │  same-origin REST + WebSocket
   ┌───────────────▼─────────────── node A (hub) ────────┐
   │  FastAPI, bound to 127.0.0.1 only                   │
   │  scheduler · probe · executor · blobs · registry    │
   └───────────────┬─────────────────────────────────────┘
                   │  TLS 1.3 + mutual certificate pinning, :8443
   ┌───────────────▼──────────┐   ┌──────────────────────┐
   │  node B (desktop / GPU)  │   │  node C (NAS)        │
   └──────────────────────────┘   └──────────────────────┘
```

**The dashboard is served by the agent, not from the web.** This is the
load-bearing decision in the whole project. A public HTTPS page can no longer
reach a local agent:

- **Safari** blocks `https://` → `http://127.0.0.1` as mixed content outright,
  with no user override ([WebKit #171934](https://bugs.webkit.org/show_bug.cgi?id=171934), open since 2017).
- **Chrome 142** (Oct 2025) began prompting for Local Network Access on any
  public-origin request to loopback; **Chrome 147** (Apr 2026) extended that gate
  to WebSockets, closing the last workaround.

Same-address-space requests are exempt, so serving the UI from the agent's own
origin removes CORS, mixed content, the permission prompt and certificate
warnings simultaneously. Syncthing (`:8384`), Jellyfin (`:8096`), Home Assistant
(`:8123`) and Ollama (`:11434`) all make the same choice.

**Node-to-node traffic does not use that server.** It runs on a raw asyncio TLS
listener, because uvicorn cannot expose the peer certificate to the application
— and the peer certificate *is* a node's identity.

## Simulated vs real

The public demo and `haze devnet` both show synthetic hardware. This table is
the contract:

| | Real | Simulated |
|---|---|---|
| CPU / RAM / disk telemetry | ✅ live from `psutil` | seeded mean-reverting walk |
| GPU telemetry | ✅ NVIDIA via NVML; Apple Silicon utilisation via `ioreg` | fabricated from a profile |
| Node identity, pairing, TLS | ✅ real Ed25519 + TLS 1.3 | n/a — demo nodes are pre-paired |
| Job execution | ✅ real subprocesses | `sleep(work / speed_factor)` |
| The scheduler's decision | ✅ **the same algorithm in both** | ✅ same |

The last row is the important one. The scheduler is a pure function, and a
golden corpus generated by the Python tests is replayed against the TypeScript
simulation in CI — so the browser demo is provably running the same placement
logic as a real cluster, not a hand-waved imitation.

**Known limits, stated plainly:** resource caps are enforceable with cgroups v2
on Linux and Job Objects on Windows, but macOS has no equivalent — there,
`setrlimit` and `nice` are all that exist, and the caps are advisory. GPU
utilisation on Apple Silicon is available without root; VRAM breakdown is not.

## Roadmap

| | Milestone | State |
|---|---|---|
| M0 | Agent, loopback dashboard, live telemetry, CI | ✅ done |
| M1 | Ed25519 identity, TLS 1.3 transport, SAS pairing | ✅ done |
| M2 | LAN discovery, resource probes, `haze devnet` | next |
| M3 | Job submission, execution, progress, file transfer | |
| M4 | Scheduler + `haze explain` + conformance corpus | |
| M5 | The in-browser simulated cluster (deployed demo) | |
| M6 | Real two-machine benchmark, chaos commands, docs | |

**Deliberately out of scope:** interactive application/game streaming. It is a
product, not a feature — the leading open-source implementation is ~2.5 MB of
C++ built by an organisation since 2020, its macOS support is experimental with
broken input on Apple Silicon, and streaming over the internet cannot be made
free because 10–30% of connections fall back to a bandwidth-metered TURN relay.
What ships instead is live job telemetry and rendered frames appearing in the
dashboard as the remote machine produces them.

## Development

```bash
make setup     # venv + npm ci
make check     # ruff, mypy strict, pytest, eslint, tsc, vitest
make build     # build the dashboard into the Python package
make run       # start an agent
```

## Security

Haze lets one of your machines run processes on another, so the trust model is
the load-bearing part of the design, not a layer on top:

- **Identity** is an Ed25519 keypair per node; the node ID is its public key's
  hash, with Luhn check characters so a human can read one aloud safely.
- **Pairing** shows the same six digits on both screens, derived *from* both
  public keys. Both users must confirm. A machine-in-the-middle cannot produce
  matching codes.
- **The handshake** has the client sign the *server's* public key, which is what
  defeats a relay attack — a signature is bound to the TLS session that made it.
- **The loopback API** is authenticated even on `127.0.0.1`, with an Origin
  check on the WebSocket upgrade. Upgrades carry no CORS preflight, and Firefox
  currently lets any HTTPS page open `ws://127.0.0.1` with no prompt; without
  that check any site you visit could drive your cluster.

[SECURITY.md](SECURITY.md) has the full model — including an equally specific
list of what Haze does **not** defend against, such as resource caps on macOS,
which cannot be enforced the way they can on Linux and Windows.

## Licence

MIT.
