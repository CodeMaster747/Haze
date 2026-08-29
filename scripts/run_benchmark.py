#!/usr/bin/env python3
"""Measure Haze offloading, and write the raw data alongside the summary.

Produces `bench/results.csv` (every individual run) and `bench/results.md` (the
table). Both are committed, because a benchmark table nobody can reproduce or
inspect is a claim rather than a measurement.

What it measures
----------------
For each workload size, the same job run locally and on a paired peer,
repeated, recording both the compute time the worker reports and the wall-clock
round trip the submitter experiences. The gap between those two is the point:
it is what a scheduler comparing raw speed would miss.

Usage:
    haze up                     # on both machines
    haze pair --serve / --host  # once
    python scripts/run_benchmark.py --repeats 5
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "bench"


@dataclass
class Run:
    workload: str
    rounds: int
    target: str
    repeat: int
    compute_s: float
    wall_s: float
    throughput: str


def _api(port: int, token: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    origin = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(
        f"{origin}/api/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": origin,
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.loads(response.read() or b"null")


def _describe_machine() -> str:
    bits = [platform.system(), platform.machine()]
    if platform.system() == "Darwin":
        try:
            model = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, timeout=5, check=False,
            )
            bits.append(model.stdout.decode().strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return " · ".join(b for b in bits if b)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7433, help="Local agent's dashboard port.")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--home", default="", help="HAZE_HOME, if not the default.")
    args = parser.parse_args()

    home = Path(args.home).expanduser() if args.home else Path.home() / ".haze"
    try:
        token = json.loads((home / "config.json").read_text())["dashboard_token"]
    except (OSError, KeyError, json.JSONDecodeError):
        print(f"could not read {home}/config.json — is an agent running?", file=sys.stderr)
        return 1

    peers = _api(args.port, token, "GET", "/peers")["peers"]
    # Whether the peer is a genuinely different machine changes what these
    # numbers mean entirely, so it is detected rather than assumed. Two agents
    # on one host share a CPU: there is no speedup to measure, only overhead.
    same_host = {p["node_id"]: p["last_host"] in _LOOPBACK for p in peers}
    targets: list[tuple[str, str]] = [("", "local")]
    targets += [(p["node_id"], p["name"]) for p in peers]
    if len(targets) == 1:
        print("no paired peers — this will measure the local machine only.", file=sys.stderr)

    # Sizes chosen to straddle the crossover: the smallest should lose to
    # overhead, the largest should win on compute.
    workloads = [("small", 40), ("medium", 200), ("large", 600)]

    runs: list[Run] = []
    for workload, rounds in workloads:
        for node_id, target in targets:
            for repeat in range(1, args.repeats + 1):
                started = time.monotonic()
                job = _api(args.port, token, "POST", "/jobs", {
                    "runtime": "hashbench", "args": {"rounds": rounds},
                    "node_id": node_id, "cpu_cores": 1, "wall_seconds": 900,
                    "label": f"bench {workload}",
                })
                while True:
                    time.sleep(0.15)
                    record = _api(args.port, token, "GET", f"/jobs/{job['job_id']}")
                    if record["state"] in {"succeeded", "failed", "rejected", "cancelled"}:
                        break
                wall = time.monotonic() - started

                if record["state"] != "succeeded":
                    print(f"  {workload}/{target} #{repeat} failed: {record['error']}",
                          file=sys.stderr)
                    continue

                runs.append(Run(
                    workload=workload, rounds=rounds, target=target, repeat=repeat,
                    compute_s=float(record["duration_s"] or 0.0), wall_s=round(wall, 3),
                    throughput=str(record["progress"]["rate"] or ""),
                ))
                print(f"  {workload:<7} {target:<12} #{repeat}  "
                      f"compute {runs[-1].compute_s:6.2f}s  wall {wall:6.2f}s")

    if not runs:
        print("no successful runs", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    _write_csv(runs)
    _write_markdown(runs, targets, args.repeats, same_host)
    print(f"\nwrote {OUT_DIR / 'results.csv'} and {OUT_DIR / 'results.md'}")
    return 0


def _write_csv(runs: list[Run]) -> None:
    with (OUT_DIR / "results.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["workload", "rounds", "target", "repeat", "compute_s", "wall_s",
                         "throughput"])
        for run in runs:
            writer.writerow([run.workload, run.rounds, run.target, run.repeat,
                             run.compute_s, run.wall_s, run.throughput])


def _write_markdown(
    runs: list[Run],
    targets: list[tuple[str, str]],
    repeats: int,
    same_host: dict[str, bool],
) -> None:
    names = [name for _, name in targets]
    lines = [
        "# Benchmark",
        "",
        (f"`hashbench`, {repeats} repeats per cell. Generated by "
         "`scripts/run_benchmark.py`; raw runs in `results.csv`."),
        "",
        f"Submitting machine: {_describe_machine()}",
        "",
        _provenance(targets, same_host),
        "",
        ("**compute** is what the worker reports. **wall** is what the person who "
         "submitted the job actually waits, including reaching the machine and "
         "getting the answer back. Medians."),
        "",
        "| workload | " + " | ".join(f"{n} compute | {n} wall" for n in names) + " |",
        "|---" * (1 + 2 * len(names)) + "|",
    ]

    for workload in ("small", "medium", "large"):
        cells: list[str] = []
        for name in names:
            subset = [r for r in runs if r.workload == workload and r.target == name]
            if not subset:
                cells += ["—", "—"]
                continue
            cells.append(f"{statistics.median(r.compute_s for r in subset):.2f}s")
            cells.append(f"{statistics.median(r.wall_s for r in subset):.2f}s")
        if cells:
            rounds = next((r.rounds for r in runs if r.workload == workload), 0)
            lines.append(f"| {workload} ({rounds} rounds) | " + " | ".join(cells) + " |")

    lines += ["", _interpret(runs, names, all(same_host.values()) and bool(same_host)), ""]
    (OUT_DIR / "results.md").write_text("\n".join(lines))


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _provenance(targets: list[tuple[str, str]], same_host: dict[str, bool]) -> str:
    """State plainly whether this measured real hardware or just the protocol."""
    if len(targets) < 2:
        return "> Only one machine took part."
    if all(same_host.get(node_id, False) for node_id, _ in targets[1:]):
        return (
            "> **Every peer here is another agent on the same physical machine.** They share\n"
            "> one CPU, so there is no hardware speedup to measure and there never could be.\n"
            "> What this table measures is **Haze's own overhead** — the cost of pairing,\n"
            "> submitting, streaming progress and returning a result. Read the wall-vs-compute\n"
            "> gap, not the ratios."
        )
    return "> Peers are separate physical machines on the LAN."


def _interpret(runs: list[Run], names: list[str], same_host_only: bool) -> str:
    """State what the numbers mean, including when they are unflattering."""
    if len(names) < 2:
        return (
            "Only one machine took part, so this measures the local agent's overhead "
            "rather than any speedup. Pair a second machine and re-run for a comparison."
        )

    remote = names[1]
    notes: list[str] = []
    overheads: list[float] = []
    for workload in ("small", "medium", "large"):
        local = [r.wall_s for r in runs if r.workload == workload and r.target == "local"]
        other = [r.wall_s for r in runs if r.workload == workload and r.target == remote]
        if not local or not other:
            continue
        local_wall = statistics.median(local)
        other_wall = statistics.median(other)
        other_compute = statistics.median(
            r.compute_s for r in runs if r.workload == workload and r.target == remote
        )
        overhead = other_wall - other_compute
        overheads.append(overhead)
        ratio = local_wall / other_wall
        notes.append(
            f"- **{workload}**: {overhead:.2f}s of Haze overhead on top of "
            f"{other_compute:.2f}s of compute "
            f"({overhead / other_wall * 100:.0f}% of the round trip); "
            f"{ratio:.2f}× vs running locally"
        )

    fixed = min(overheads) if overheads else 0.0
    tail = (
        "\n\nOverhead is roughly **fixed** (about "
        f"{fixed:.2f}s here), so it dominates a short job and disappears into a long one. "
        "That is the whole argument for weighing transfer cost: below some size, "
        "offloading cannot win no matter how fast the other machine is, and a scheduler "
        "comparing raw speed would send the work anyway."
    )
    if same_host_only:
        tail += (
            "\n\nBecause every peer here shares this machine's CPU, the ratios say nothing "
            "about hardware. Re-run with a genuinely separate machine to measure a speedup; "
            "the overhead figures above hold either way."
        )
    return "## What this shows\n\n" + "\n".join(notes) + tail


if __name__ == "__main__":
    sys.exit(main())
