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

### Windows

Haze is most useful when the machine lending its GPU is the fast one, and that
machine is usually a Windows gaming PC whose owner has never opened PowerShell.
This section is written for them. Nothing here needs administrator.

**1. Open PowerShell.** Press the **Windows key**, type `powershell`, press
Enter. A blue window opens. Do *not* pick "Run as administrator" — Haze does not
want it, and using it would install Haze for the wrong account.

**2. Paste this one line and press Enter.**

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CodeMaster747/Haze/main/scripts/install.ps1 | iex"
```

It installs [uv](https://docs.astral.sh/uv/), then Python, then Haze, and prints
what to do next. It takes a minute or two.

> **This is a real trust decision, so read it before you take it.** That command
> downloads a script and runs it immediately — whatever is at that URL at that
> moment, with your account's permissions. "It's from GitHub" is not a security
> argument. The honest answer is not to reassure you but to let you check:
>
> ```powershell
> irm https://raw.githubusercontent.com/CodeMaster747/Haze/main/scripts/install.ps1 -OutFile haze-install.ps1
> notepad haze-install.ps1                       # read it
> powershell -ExecutionPolicy Bypass -File .\haze-install.ps1
> ```
>
> It is about 200 lines, mostly comments, and it is
> [`scripts/install.ps1`](scripts/install.ps1) in this repo with its full
> history. `-ExecutionPolicy Bypass` applies to that one PowerShell process and
> changes nothing about your machine.
>
> You can also skip the script entirely. If you already have uv, the whole
> install is `uv tool install haze-agent`. The script exists only so that
> someone who has never seen a terminal does not have to know that.

**3. Start it.**

```powershell
haze up
```

A browser tab opens on the dashboard at `http://127.0.0.1:7433`. That address is
loopback-only and carries a token — nobody else on your network, or the
internet, can open it. See [SECURITY.md](SECURITY.md#the-loopback-api).

**4. Keep it running across reboots.**

```powershell
haze autostart enable      # start Haze minimised at every login
haze autostart disable     # stop doing that
haze autostart status      # which is it right now?
```

`enable` writes a small text file called `Haze.cmd` into your Startup folder and
a "Haze Console" entry into your Start menu. Both are plain text you can open in
Notepad, and the Startup one contains instructions for removing itself. There are
three ways to turn it off and they all work: run `haze autostart disable`, delete
the file (press **Win+R**, type `shell:startup`, Enter), or switch it off in Task
Manager's **Startup apps** tab.

**5. Watch what it is doing.** Press the Windows key and type `Haze Console`, or
run `haze open`. Either opens the dashboard for whichever agent is running —
Haze looks up the live port and token rather than relying on a saved link. While
Haze is running there is a minimised **Haze** window in your taskbar; closing it
stops the agent until your next login.

**Where jobs actually run.** Each job gets its own folder under
`%USERPROFILE%\.haze\jobs\`, and that folder is deleted when the job finishes.
Haze's own state — your machine's identity key, config, and peer list — lives in
`%USERPROFILE%\.haze`. Nothing is written outside your user profile, and nothing
is installed into Windows itself.

**Stopping and unpairing.**

| To do this | Run this |
|---|---|
| Stop Haze now | Close the minimised **Haze** window, or press Ctrl+C in it |
| Stop it coming back at login | `haze autostart disable` |
| See which machines are paired | `haze peers` |
| Forget a machine permanently | `haze unpair <short-id>` |
| Remove Haze entirely | `haze autostart disable`, then `uv tool uninstall haze-agent` |

Unpairing is immediate and one-sided in your favour: the removed machine's next
connection is refused at the handshake. Deleting `%USERPROFILE%\.haze` discards
your identity key too, so every other machine will need to pair with you again.

**Why there is no `winget install haze`.** It was investigated and it does not
work without breaking the rule above. A winget manifest has to point at a
downloadable installer — the allowed types are `exe`, `msi`, `msix`, `inno`,
`nullsoft`, `wix`, `burn`, and `zip`/`portable` archives wrapping one of those.
There is no manifest type that runs `pip install`, so publishing Haze would mean
freezing it into an unsigned `.exe`, which is exactly the malware warning this
project refuses to hand you. Winget's own submission checks run every installer
through multiple antivirus engines, and frozen-Python executables are a
well-known source of those rejections. So: PowerShell script you can read, or
`uv tool install haze-agent`. Both are honest about what they are.

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

Not on the same network? `--host` takes any routable address, including a
Tailscale one — see [Across the internet](#across-the-internet).

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
allowlist (`hashbench`, `blender`, `ffmpeg`, `whisper`) and supplies typed
arguments; the runtime builds the command line. There is no shell anywhere in
the path, and no field a peer controls becomes a command name. Paths are
resolved strictly inside the job's own directory, so `../../../etc/passwd` is
refused rather than sanitised.

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
| Memory (Windows) | Job Objects | Real: the allocation *fails*, rather than the job being killed |
| CPU (Windows) | Job Objects | Real: a hard rate cap on the whole process tree |
| Memory (macOS) | `setrlimit` + monitoring | **Advisory.** Bounds address space, not resident set |
| CPU (macOS) | `nice` | **Not enforceable.** No cgroups, no Job Objects |

Windows and Linux are both real and they are not the same mechanism: cgroups v2
OOM-kills a job that exceeds `MemoryMax`, while a Job Object makes the
allocation fail inside the process — so a job that handles a failed allocation
gracefully keeps running, inside its cap. Haze reports both as kernel-enforced
and says which one you have.

The Windows enforcement is the one part of this table that no CI runner
exercises — [docs/verifying-windows-limits.md](docs/verifying-windows-limits.md)
is the manual procedure that proves it, including how to tell a kernel refusal
apart from Haze's own watchdog noticing afterwards.

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

### Across the internet

**mDNS and broadcast are LAN-only, by design.** Multicast does not cross
subnets and Haze does not try to make it — a discovery mechanism that
sometimes worked between networks would be worse than one that never claims
to. Off-LAN, the third row of that table is the supported path: give Haze the
address yourself.

Anything that makes the two machines mutually routable works. Tailscale is the
one worth naming because it is free for personal use and needs no port
forwarding. It is *your* account, entirely optional, and Haze neither bundles
it nor talks to it — the no-cloud rule above is about Haze, and it holds.

```bash
# on both machines
tailscale up
tailscale status          # each should list the other

# on the first machine
tailscale ip -4           # e.g. 100.64.0.5
haze up
haze pair --serve         # prints its overlay address as well as its LAN one

# on the second
haze up
haze pair --host 100.64.0.5
```

Nothing about pairing changes. Certificates are pinned to a raw Ed25519 public
key rather than to a hostname, so an overlay address needs no certificate work,
and you still compare the same six digits and four words on both screens.

**Pin the address.** Haze records where a peer last connected *from*, and
rewrites it on every inbound session. A laptop that is sometimes on your LAN
and sometimes only on Tailscale will otherwise flip between the two:

```bash
haze address studio --set 100.64.0.5    # observed traffic no longer overwrites it
haze address studio                     # shows pinned and last-seen
haze address studio --clear             # back to whatever it last connected from
```

A pinned address is tried first and the last-seen address second, so a machine
that moves between the two stays reachable without you touching anything. If
both fail, the error names both addresses and why each one did.

Known limits, stated plainly:

- **Both machines need the overlay up.** Haze has no relay and no hole
  punching; if Tailscale is down on either end there is no path, and Haze says
  so rather than blaming your router.
- **Discovery still finds nothing off-LAN.** A remote peer will not appear in
  the dashboard's discovered list. Pinning its address adds it.
- Latency and throughput over an overlay are worse than on a LAN, and the
  scheduler already accounts for measured link cost — expect it to keep more
  work local. `haze explain` will show you why.

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
