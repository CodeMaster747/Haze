# Haze

**Pool your own machines into a private compute network.**

You probably own more than one computer: a laptop with a good screen and a weak
GPU, a desktop that is fast but sits idle, maybe a box with a lot of disk. Haze
makes them work as one personal cluster — submit a job from the laptop, run it
on the desktop's GPU, get the result back — with per-node limits you set.

No cloud provider, no account, no bill. You own every node.

> **Status: complete through M6.** Pair two machines, run a real job on the
> other one — files across, progress back, results home — ask the scheduler why
> it chose what it chose, kill a machine mid-job and watch it fail cleanly, and
> play with a simulated cluster in the browser. The only thing outstanding is
> deploying the demo, which needs a Firebase project.

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

```
  SIMULATED CLUSTER
  These nodes report fabricated hardware. Nothing here is a real GPU.

  • workstation    16c   64 GiB  RTX 4090     ×4.2
  • laptop         10c   24 GiB  Apple M4     ×1.0
  • nas             4c    8 GiB  no GPU       ×0.4
  • builder        12c   32 GiB  Arc A770     ×2.1
```

Four **real** agents — real identities, real TLS, real discovery — reporting
fabricated hardware, so the whole system is legible without owning four
computers. They find each other over mDNS and UDP broadcast on loopback, which
exercises the actual discovery path rather than a fixture.

**Every simulated node is badged as such**, in the dashboard, in CLI output and
in the API payload. See [Simulated vs real](#simulated-vs-real).

Not docker-compose, deliberately: Compose V2 broke per-replica port ranges
(docker/compose #8530, still open), Docker Desktop for Mac has no GPU
passthrough, and its `--network=host` does not behave like Linux's — which
would break the multicast this is meant to exercise.

## Run something on another machine

```bash
# render 3 frames on the desktop, from the laptop
haze run blender --on desktop --blend scene.blend --frames 1-3
```

```
  blender on desktop
  ██████████████████████████ 100.0% 0.6s/frame
  done in 1.61s · 0.6s/frame
    …/jobs/58c22cf4/out/0001.png
    …/jobs/58c22cf4/out/0002.png
    …/jobs/58c22cf4/out/0003.png
```

The `.blend` is streamed to the desktop with the job, rendered there, and the
PNGs come back — all over the same mutually-authenticated TLS connection.

**Haze does not run arbitrary commands.** A job names a runtime from a fixed
allowlist (`hashbench`, `blender`, `ffmpeg`) and supplies typed arguments; the
runtime builds the command line. There is no shell anywhere in the path, and no
field a peer controls becomes a command name. Paths are resolved strictly inside
the job's own directory, so `../../../etc/passwd` is refused rather than
sanitised.

### Benchmarking

```bash
haze bench --compare
```

```
  node                   compute   round trip    throughput   vs local
  ────────────────────────────────────────────────────────────────────
  this machine             3.14s        3.21s    3063 MiB/s      1.00×
  desktop                  2.81s        3.57s    3059 MiB/s      0.90×
```

Note the desktop **computing faster and still losing**. That is the honest
result, and it is the entire argument for having a scheduler: offloading is
only worth it when the work outweighs the cost of moving it. A benchmark that
reported compute time alone would hide exactly the thing worth knowing.

### Why did it choose that?

```bash
haze explain --runtime hashbench --work 20 --input 800
```

```
  → laptop — desktop computes faster but is 133.18s slower end to end
    once transfer is counted

  ✓ laptop          score 1.000   ~21.04s
      speed      █████████████░ 0.95
      transfer   ██████████████ 1.00
      · runs here — nothing to transfer

    desktop         score 0.136   ~154.22s
      speed      ██████████████ 1.00
      transfer   █░░░░░░░░░░░░░ 0.13
      · 134.22s moving 819200 KiB each way (87% of the total)
```

The scheduler **minimises predicted end-to-end time** — compute plus moving the
bytes — rather than scoring a weighted average of niceness. Every candidate is
reported, winners and losers alike, with the reason each one lost.

Being ineligible is elimination, not a low score: "you do not have Blender
installed" is not something a fast enough machine can outweigh.

**The scheduler is a pure function**, and that is load-bearing. `pytest` writes
a golden corpus of `(cluster, job) → decision` records, and a vitest suite
replays it against the TypeScript implementation the browser demo runs. Change
one and the conformance test fails until you change the other — so "the demo
runs the real algorithm" is a checked claim, not a marketing one.

### Measured overhead

`scripts/run_benchmark.py` writes [bench/results.md](bench/results.md) and the
raw per-run CSV beside it. Both are committed, because a benchmark nobody can
inspect is a claim rather than a measurement.

| workload | local wall | remote compute | remote wall | Haze overhead |
|---|---|---|---|---|
| 40 rounds | 0.47s | 0.40s | 0.96s | 0.56s (58% of the round trip) |
| 200 rounds | 2.21s | 2.01s | 2.54s | 0.53s (21%) |
| 600 rounds | 6.32s | 6.02s | 6.46s | 0.44s (7%) |

**Both agents here are on one Mac**, so there is no hardware speedup to measure
and the script says so in its own output. What it does measure is Haze's own
overhead: roughly **fixed at half a second**, so it dominates a short job and
vanishes into a long one.

That is the whole argument for weighing transfer cost. Below some size,
offloading cannot win no matter how fast the other machine is — and a scheduler
comparing raw speed would send the work anyway.

### When a machine goes away

```bash
haze run hashbench --on desktop --rounds 6000   # then kill the desktop's agent
```

```
  failed: desktop disconnected while running this job. Its agent may have
  stopped or the machine gone to sleep — the work is lost and will need
  resubmitting.
```

Fails in well under a second rather than hanging, and says something you can
act on. Before there was a test for this, the message was asyncio's own
`0 bytes read on a total of 4 expected bytes`. Two integration tests now hold
that line, and a third asserts the surviving agent keeps working.

### Resource limits, honestly

| | Enforced by | Reality |
|---|---|---|
| Wall clock | Haze itself | Real everywhere — needs no OS support |
| Memory (Linux) | cgroups v2 | Real: the kernel kills on breach |
| CPU (Linux) | cgroups v2 | Real: a genuine share, not a priority hint |
| Memory (macOS) | `setrlimit` + monitoring | **Advisory.** Bounds address space, not resident set |
| CPU (macOS) | `nice` | **Not enforceable.** No cgroups, no Job Objects |
| Memory/CPU (Windows) | monitoring only | Job Objects not implemented yet |

The dashboard shows which of these you actually got. A cap that silently is not
enforced is worse than no cap — it makes someone comfortable running a job they
should have thought harder about.

## The public site

Two screens, and no backend behind either: nothing to pay for, nothing to
cold-start, nothing that rots when a free tier changes terms.

**`/` is the landing page.** Its hero is not a screenshot of the scheduler — it
*is* the scheduler. The panel calls the same `decide()` on the demo cluster's
three machines, and its one control changes the link between them:

```
  Fast LAN  → workstation — 0.93s faster than laptop end to end
  Wi-Fi     → laptop — workstation computes faster but is 61.57s slower
              end to end once transfer is counted
```

A machine that computes 4× faster winning by under a second, then losing
outright one step down, is the entire argument for weighing transfer cost. The
page lets a visitor falsify it in a click rather than asserting it in a
sentence.

**`/cluster` is the simulated cluster** — something moving within a second of
arriving. It is not a mock either. Placement goes through the same `decide()`,
held to the Python implementation by the conformance corpus above. What is
simulated is the hardware and the passage of time; the scheduling is real.

You can submit jobs, drag the network between machines from LAN to slow link
and watch an encode job come home, take a machine offline mid-job and watch the
work get rescheduled, and pause or fast-forward the virtual clock.

**The landing page ships only in the hosted build.** `__HAZE_DEMO__` gates the
route switch, so the agent's own dashboard opens straight onto telemetry as it
always did — someone who has run `haze up` has already been introduced to the
product, and a marketing page in front of their cluster would be an
interruption rather than an entrance. The agent bundle contains no landing-page
code at all.

**The hosted bundle provably cannot contact a local agent.** `__HAZE_DEMO__` is
a compile-time constant, so the minifier strips the entire agent-facing path,
and `make verify-demo-bundle` (also a CI step) asserts the built artifact
contains no loopback address, no `/api/v1`, and no `WebSocket` constructor. That
matters because the demo is served over HTTPS — a stray request to
`127.0.0.1` would be blocked by Safari and prompted by Chrome, so a visitor's
first impression would be a security warning about a request that was never
going to work.

## Discovery

Three mechanisms, run together rather than as a fallback chain:

| | Finds | Fails when |
|---|---|---|
| **mDNS** (`_haze._tcp`) | across the subnet | multicast is filtered — mesh APs with IGMP snooping, `avahi-daemon` holding UDP 5353 |
| **UDP broadcast** | the local segment | the network blocks broadcast, or the peer is on another subnet |
| **By address** | anything routable | never — which is why it is always available, not hidden behind a failure state |

They fail in uncorrelated ways, so the union finds strictly more — and the
*difference* is diagnostic. A node seen by broadcast but never by mDNS means
multicast is being dropped, and the dashboard says so.

One case no discovery mechanism can fix: if an access point isolates clients
from each other (default on most guest networks), Haze detects it — the node
advertises but no connection can be opened — and names it, rather than showing
a timeout that sends you hunting in the wrong place.

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
| GPU telemetry | ✅ NVIDIA via NVML; Apple Silicon via `ioreg`, no root needed | fabricated from a profile |
| Hardware encoders | ✅ probed from `ffmpeg -encoders` | listed in the profile |
| Discovery | ✅ real mDNS + UDP broadcast | pre-populated |
| Job execution | ✅ real subprocesses, real files, real output | a finished record |
| Node identity, pairing, TLS | ✅ real Ed25519 + TLS 1.3 | n/a — demo nodes are pre-paired |
| Job execution | ✅ real subprocesses | `sleep(work / speed_factor)` |
| The scheduler's decision | ✅ **the same algorithm in both** | ✅ same |
| Placement reasoning | ✅ real, from live peer capabilities | same code, fixture inputs |

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
| M2 | LAN discovery, resource probes, `haze devnet` | ✅ done |
| M3 | Job submission, execution, progress, file transfer | ✅ done |
| M4 | Scheduler + `haze explain` + conformance corpus | ✅ done |
| M5 | Landing page + the in-browser simulated cluster | ✅ built — awaiting a Firebase project to deploy to |
| M6 | Benchmark with committed data, fault injection, docs | ✅ done |

**Deliberately out of scope:** interactive application/game streaming. It is a
product, not a feature — the leading open-source implementation is ~2.5 MB of
C++ built by an organisation since 2020, its macOS support is experimental with
broken input on Apple Silicon, and streaming over the internet cannot be made
free because 10–30% of connections fall back to a bandwidth-metered TURN relay.
What ships instead is live job telemetry and rendered frames appearing in the
dashboard as the remote machine produces them.

## Documentation

- [docs/architecture.md](docs/architecture.md) — how the pieces fit, and which
  constraint forced each shape
- [SECURITY.md](SECURITY.md) — the threat model, and an equally specific list of
  what Haze does *not* defend against
- [DEPLOY.md](DEPLOY.md) — the zero-cost rule, and the three ways to break it
- [bench/results.md](bench/results.md) — measured overhead, with raw data

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
