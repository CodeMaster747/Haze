"""`haze run`, `haze jobs`, `haze bench`.

All drive the running agent through its loopback API, so the agent stays the
single writer and the CLI is a thin client.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer

from haze import apiclient, log

BAR_WIDTH = 26


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _bar(fraction: float | None) -> str:
    if fraction is None:
        return "·" * BAR_WIDTH
    filled = int(max(0.0, min(1.0, fraction)) * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _resolve_node(target: str) -> tuple[str, str, str]:
    """Map a name or short id to (node_id, display name, placement mode).

    '' means locally and 'auto' hands the choice to the scheduler, which is why
    "auto" is a reserved node name: a peer that happens to be called that is
    addressed by its short id instead.
    """
    if not target:
        return "", "this machine", "manual"
    if target.lower() == "auto":
        return "", "auto", "auto"
    peers = apiclient.get("/peers")["peers"]
    for peer in peers:
        if target.upper() in {peer["short_id"].upper(), peer["name"].upper()}:
            return str(peer["node_id"]), str(peer["name"]), "manual"
    known = ", ".join(f"{p['name']} ({p['short_id']})" for p in peers) or "none paired"
    _fail(f"  no paired node matching {target!r}. Known: {known}")
    raise AssertionError("unreachable")


def _announce_placement(job: dict[str, Any]) -> None:
    """Print who won and the one-line reason, before progress starts moving.

    The names come out of the decision itself rather than being re-derived
    here: the scheduler already knows what it called each node, and two places
    naming the same machine differently is how a trace stops being trusted.
    """
    decision = job.get("placement")
    if not decision:
        return
    typer.secho(f"  → {decision['summary']}", fg=typer.colors.BRIGHT_MAGENTA)
    winner = next(
        (a for a in decision["assessments"] if a["node_id"] == decision["chosen"]), None
    )
    if winner is not None:
        typer.secho(
            f"    running on {winner['name']} · ~{winner['estimated_seconds']:.1f}s predicted\n",
            fg=typer.colors.BRIGHT_BLACK,
        )


def _follow(job_id: str, quiet: bool = False) -> dict[str, Any]:
    """Poll a job to completion, drawing progress."""
    last_line = ""
    while True:
        job = apiclient.get(f"/jobs/{job_id}")
        progress = job["progress"]
        fraction = progress["fraction"]
        percent = "      " if fraction is None else f"{fraction * 100:5.1f}%"
        line = f"  {_bar(fraction)} {percent}"
        if not quiet and line != last_line:
            last_line = line
            detail = progress.get("rate") or progress.get("detail") or progress.get("stage") or ""
            # \r returns to the start of the line but leaves whatever was there;
            # \x1b[K clears to end of line so a shorter update cannot leave the
            # tail of a longer one behind.
            typer.echo(f"\r{line} {detail[:44]}\x1b[K", nl=False)
        if job["state"] in {"succeeded", "failed", "cancelled", "rejected"}:
            if not quiet:
                typer.echo()
            return dict(job)
        time.sleep(0.35)


def run_command(
    runtime: str = typer.Argument(..., help="Which runtime: hashbench, blender, ffmpeg, whisper."),
    on: str = typer.Option("", "--on",
        help="Node name or short id, or 'auto' to let the scheduler choose. "
             "Omit to run here."),
    rounds: int = typer.Option(0, "--rounds", help="hashbench: how much work."),
    blend: str = typer.Option("", "--blend", help="blender: .blend file in the job directory."),
    frames: str = typer.Option("", "--frames", help="blender: e.g. 1-10."),
    device: str = typer.Option("CPU", "--device",
        help="blender: CPU, METAL, CUDA, OPTIX... · whisper: cpu, cuda, auto."),
    src: str = typer.Option("", "--input", help="ffmpeg: input file in the job directory."),
    encoder: str = typer.Option("libx264", "--encoder", help="ffmpeg encoder."),
    audio: str = typer.Option("", "--audio", help="whisper: audio file to transcribe."),
    model: str = typer.Option("base", "--model", help="whisper: tiny...large-v3, turbo."),
    language: str = typer.Option("auto", "--language", help="whisper: en, es, ja... or auto."),
    fmt: str = typer.Option("txt", "--format", help="whisper: txt, srt, vtt, json."),
    file: list[str] = typer.Option([], "--file", "-f",
        help="Send a local file with the job. Repeatable."),
    cores: int = typer.Option(1, "--cores"),
    timeout: int = typer.Option(3600, "--timeout", help="Wall-clock limit in seconds."),
) -> None:
    """Run a job here or on a paired machine."""
    log.setup()
    args: dict[str, Any] = {}
    if runtime == "hashbench":
        args["rounds"] = rounds or 200
    elif runtime == "blender":
        if not blend:
            _fail("  blender needs --blend <file>")
        args["blend_file"] = Path(blend).name
        # The .blend is sent with the job; the runtime resolves it by name
        # inside the job's own directory, never by the path given here.
        if blend not in file:
            file = [*file, blend]
        args["device"] = device
        if frames:
            start, _, end = frames.partition("-")
            args["frame_start"] = int(start)
            args["frame_end"] = int(end or start)
    elif runtime == "ffmpeg":
        if not src:
            _fail("  ffmpeg needs --input <file>")
        args["input"] = Path(src).name
        if src not in file:
            file = [*file, src]
        args["encoder"] = encoder
    elif runtime == "whisper":
        if not audio:
            _fail("  whisper needs --audio <file>")
        args["audio"] = Path(audio).name
        # Sent with the job; the runtime resolves it by name inside the job's
        # own directory, never by the path given here.
        if audio not in file:
            file = [*file, audio]
        args["model"] = model
        args["language"] = language
        args["format"] = fmt
        # --device is shared with blender, whose names are upper case. The
        # default "CPU" is a valid whisper device once folded down.
        args["device"] = device.lower()

    try:
        node_id, where, placement = _resolve_node(on)
        if placement == "auto":
            # No node named yet -- the next two lines, once the agent has
            # decided, say which one won and why.
            typer.secho(f"\n  {runtime} · asking the scheduler\n",
                        fg=typer.colors.BRIGHT_WHITE)
        else:
            typer.secho(f"\n  {runtime} on {where}", fg=typer.colors.BRIGHT_WHITE)
        job = apiclient.post(
            "/jobs",
            {"runtime": runtime, "args": args, "node_id": node_id, "files": file,
             "placement": placement, "cpu_cores": cores, "wall_seconds": timeout,
             "label": f"{runtime} via cli"},
        )
        if job["state"] == "rejected":
            _fail(f"  rejected: {job['error']}")

        _announce_placement(job)
        final = _follow(job["job_id"])
    except apiclient.AgentNotRunningError as exc:
        _fail(f"  {exc}")
        return
    except apiclient.ApiError as exc:
        _fail(f"  {exc}")
        return

    if final["state"] == "succeeded":
        typer.secho(
            f"  done in {final['duration_s']}s"
            + (f" · {final['progress']['rate']}" if final["progress"]["rate"] else ""),
            fg=typer.colors.GREEN,
        )
        for output in final["outputs"]:
            typer.echo(f"    {output}")
    else:
        typer.secho(f"  {final['state']}: {final['error']}", fg=typer.colors.RED)
        raise typer.Exit(1)


def jobs_command(
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh until interrupted."),
) -> None:
    """List jobs on this machine."""
    log.setup()
    try:
        while True:
            state = apiclient.get("/jobs")
            typer.echo()
            typer.secho(f"  caps: {state['caps']['enforcement']}", fg=typer.colors.BRIGHT_BLACK)
            typer.echo()
            if not state["jobs"]:
                typer.secho("  no jobs yet — try `haze run hashbench`", fg=typer.colors.BRIGHT_BLACK)
            for job in state["jobs"][:20]:
                colour = {
                    "succeeded": typer.colors.GREEN, "failed": typer.colors.RED,
                    "rejected": typer.colors.RED, "running": typer.colors.CYAN,
                }.get(job["state"], typer.colors.WHITE)
                typer.secho(f"  {job['state']:<10}", fg=colour, nl=False)
                duration = job["duration_s"]
                elapsed = "" if duration is None else f"{duration}s"
                typer.echo(f"{job['job_id'][:8]}  {job['runtime']:<10} "
                           f"{(job['label'] or '')[:28]:<28} {elapsed}")
                if job["error"]:
                    typer.secho(f"             {job['error'][:70]}", fg=typer.colors.RED)
            if not watch:
                typer.echo()
                return
            time.sleep(1.0)
    except KeyboardInterrupt:
        typer.echo()
    except apiclient.AgentNotRunningError as exc:
        _fail(str(exc))


def bench_command(
    rounds: int = typer.Option(400, "--rounds", help="Work per run."),
    compare: bool = typer.Option(False, "--compare", help="Run on every paired node too."),
) -> None:
    """Benchmark this machine, and optionally every paired machine.

    The comparison is the point: it measures the *whole* round trip, including
    getting the work there and the answer back. A node that computes twice as
    fast but sits behind a slow link can still lose, and a benchmark that hid
    that would be measuring the wrong thing.
    """
    log.setup()
    try:
        targets: list[tuple[str, str]] = [("", "this machine")]
        if compare:
            targets += [(p["node_id"], p["name"]) for p in apiclient.get("/peers")["peers"]]

        typer.echo()
        typer.secho(f"  hashbench · {rounds} rounds · {rounds * 32} MiB hashed\n",
                    fg=typer.colors.BRIGHT_WHITE)

        results: list[tuple[str, dict[str, Any]]] = []
        for node_id, name in targets:
            typer.secho(f"  {name} ", fg=typer.colors.BRIGHT_BLACK, nl=False)
            started = time.monotonic()
            job = apiclient.post(
                "/jobs",
                {"runtime": "hashbench", "args": {"rounds": rounds}, "node_id": node_id,
                 "cpu_cores": 1, "wall_seconds": 900, "label": "bench"},
            )
            if job["state"] == "rejected":
                typer.secho(f"— rejected: {job['error']}", fg=typer.colors.RED)
                continue
            final = _follow(job["job_id"], quiet=True)
            final["_wall"] = round(time.monotonic() - started, 2)
            if final["state"] != "succeeded":
                typer.secho(f"— {final['state']}: {final['error'][:50]}", fg=typer.colors.RED)
                continue
            typer.secho("✓", fg=typer.colors.GREEN)
            results.append((name, final))

        if not results:
            _fail("  no run completed")

        typer.echo()
        typer.secho(f"  {'node':<20}{'compute':>10}{'round trip':>13}{'throughput':>14}{'vs local':>11}",
                    fg=typer.colors.BRIGHT_WHITE)
        typer.secho("  " + "─" * 68, fg=typer.colors.BRIGHT_BLACK)
        baseline = results[0][1]["_wall"]
        for name, job in results:
            speedup = baseline / job["_wall"] if job["_wall"] else 0.0
            colour = typer.colors.GREEN if speedup >= 1.0 else typer.colors.YELLOW
            typer.echo(f"  {name[:19]:<20}{job['duration_s']:>9.2f}s{job['_wall']:>12.2f}s"
                       f"{job['progress']['rate']:>14}", nl=False)
            typer.secho(f"{speedup:>10.2f}×", fg=colour)

        typer.echo()
        if len(results) > 1:
            typer.secho(
                "  'round trip' includes reaching the node and getting the answer back.\n"
                "  A node can compute faster and still lose on short jobs — which is\n"
                "  exactly why the scheduler weighs transfer cost, not just speed.",
                fg=typer.colors.BRIGHT_BLACK,
            )
        typer.echo()
    except apiclient.AgentNotRunningError as exc:
        _fail(str(exc))
    except apiclient.ApiError as exc:
        _fail(f"  {exc}")


def explain_command(
    job_id: str = typer.Argument("", help="A job id, or omit to preview a placement."),
    runtime: str = typer.Option("hashbench", "--runtime", help="Runtime to preview."),
    cores: int = typer.Option(1, "--cores"),
    ram_gib: float = typer.Option(1.0, "--ram", help="Memory needed, in GiB."),
    gpu: bool = typer.Option(False, "--gpu", help="Require a GPU."),
    encoder: str = typer.Option("", "--encoder", help="Preferred hardware encoder."),
    input_mib: float = typer.Option(0.0, "--input", help="Input size in MiB."),
    work: float = typer.Option(10.0, "--work", help="Rough compute size in work units."),
) -> None:
    """Show where a job would run, and why each node won or lost.

    The scheduler is a pure function, so this is the real decision rather than
    a description of one -- the same call the agent makes when placing work.
    """
    log.setup()
    try:
        if job_id:
            job = apiclient.get(f"/jobs/{job_id}")
            resources = job["resources"]
            body = {
                "runtime": job["runtime"],
                "cpu_cores": resources["cpu_cores"],
                "ram_bytes": resources["ram_bytes"],
                "needs_gpu": resources["needs_gpu"],
                "preferred_encoders": resources["preferred_encoders"],
                "input_bytes": 0,
                "work_units": max(1.0, float(job["duration_s"] or 10.0)),
            }
            typer.secho(f"\n  replaying the placement for job {job_id[:8]} ({job['runtime']})",
                        fg=typer.colors.BRIGHT_BLACK)
        else:
            body = {
                "runtime": runtime,
                "cpu_cores": cores,
                "ram_bytes": int(ram_gib * 1024**3),
                "needs_gpu": gpu,
                "preferred_encoders": [encoder] if encoder else [],
                "input_bytes": int(input_mib * 1024**2),
                "work_units": work,
            }
            typer.secho(f"\n  where would a {runtime} job go?", fg=typer.colors.BRIGHT_BLACK)

        decision = apiclient.post("/schedule", body)
    except apiclient.AgentNotRunningError as exc:
        _fail(str(exc))
        return
    except apiclient.ApiError as exc:
        _fail(f"  {exc}")
        return

    typer.echo()
    typer.secho(f"  → {decision['summary']}\n", fg=typer.colors.BRIGHT_MAGENTA)

    for entry in decision["assessments"]:
        chosen = entry["node_id"] == decision["chosen"]
        marker = "✓" if chosen else (" " if entry["eligible"] else "✗")
        colour = (
            typer.colors.GREEN if chosen
            else typer.colors.WHITE if entry["eligible"]
            else typer.colors.RED
        )
        typer.secho(f"  {marker} {entry['name']:<16}", fg=colour, nl=False)

        if entry["eligible"]:
            typer.echo(f"score {entry['score']:.3f}   ~{entry['estimated_seconds']:.2f}s")
            dims = entry["dimensions"]
            for key in ("speed", "headroom", "transfer", "affinity"):
                value = dims.get(key, 0.0)
                bar = "█" * int(value * 14) + "░" * (14 - int(value * 14))
                typer.secho(f"      {key:<10} {bar} {value:.2f}", fg=typer.colors.BRIGHT_BLACK)
        else:
            typer.echo("ineligible")

        for reason in entry["reasons"]:
            typer.secho(f"      · {reason}", fg=typer.colors.BRIGHT_BLACK)
        typer.echo()

    typer.secho(
        "  speed/headroom/transfer/affinity explain the ranking; the ranking itself\n"
        "  minimises predicted end-to-end time (compute + moving the bytes).\n",
        fg=typer.colors.BRIGHT_BLACK,
    )
