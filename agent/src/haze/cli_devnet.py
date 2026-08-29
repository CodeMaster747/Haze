"""`haze devnet` -- a whole cluster on one machine.

The point is that almost nobody evaluating this project owns four computers,
and the scheduler is uninteresting until there is something to choose between.
Four agents with distinct synthetic hardware make the system legible on a
single laptop.

They are real agents: real identities, real TLS, real discovery over UDP
broadcast on loopback. Only the *hardware readings* are fabricated, and every
one of them is badged SIMULATED in the dashboard, in this command's output,
and in the API payload.
"""

from __future__ import annotations

import signal
import time
import types
import webbrowser

import typer

from haze import log
from haze.devnet.supervisor import DevNet, plan
from haze.probe import synthetic

devnet_app = typer.Typer(help="Run several simulated nodes on this machine.")


@devnet_app.command("up")
def up(
    count: int = typer.Option(4, "-n", "--count", min=1, max=12, help="How many nodes."),
    profiles: str = typer.Option(
        "", "--profiles", help=f"Comma-separated. Available: {', '.join(synthetic.available())}"
    ),
    open_browser: bool = typer.Option(False, "--open", help="Open the first node's console."),
) -> None:
    """Start N simulated nodes and hold them until Ctrl-C."""
    log.setup()

    try:
        nodes = plan(count, [p.strip() for p in profiles.split(",") if p.strip()] or None)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    net = DevNet(nodes)
    typer.secho(f"\n  Starting {count} simulated nodes...", fg=typer.colors.BRIGHT_BLACK)
    net.start()

    stopping = False

    def handle(_signum: int, _frame: types.FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    ready = net.wait_ready()
    if not ready:
        typer.secho("  no node came up. Run `haze up` alone to see the error.",
                    fg=typer.colors.RED, err=True)
        net.stop()
        raise typer.Exit(1)

    typer.echo()
    typer.secho("  SIMULATED CLUSTER  ", fg=typer.colors.BLACK, bg=typer.colors.MAGENTA, bold=True)
    typer.secho("  These nodes report fabricated hardware. Nothing here is a real GPU.\n",
                fg=typer.colors.MAGENTA)

    for node in nodes:
        profile = synthetic.load(node.profile)
        gpu = profile.gpu.name if profile.gpu else "no GPU"
        up_marker = "•" if node in ready else "×"
        colour = typer.colors.GREEN if node in ready else typer.colors.RED
        typer.secho(f"  {up_marker} {node.name:<14}", fg=colour, nl=False)
        typer.echo(f"{profile.cores:>3}c  {profile.ram_bytes // 2**30:>3} GiB  "
                   f"{gpu:<12} ×{profile.speed_factor}")
        typer.secho(f"    {node.console_url}", fg=typer.colors.BRIGHT_BLACK)

    if len(ready) < len(nodes):
        typer.secho(f"\n  {len(nodes) - len(ready)} node(s) did not start.",
                    fg=typer.colors.YELLOW)

    typer.secho("\n  Ctrl-C to stop them all.\n", fg=typer.colors.BRIGHT_BLACK)

    if open_browser and ready:
        webbrowser.open(ready[0].console_url)

    try:
        while not stopping:
            time.sleep(0.3)
            dead = [n for n in nodes if n.process and n.process.poll() is not None]
            if len(dead) == len(nodes):
                typer.secho("  every node exited", fg=typer.colors.RED, err=True)
                break
    finally:
        typer.secho("\n  stopping...", fg=typer.colors.BRIGHT_BLACK)
        net.stop()


@devnet_app.command("profiles")
def list_profiles() -> None:
    """Show the available synthetic hardware profiles."""
    log.setup()
    typer.echo()
    for name in synthetic.available():
        p = synthetic.load(name)
        gpu = f"{p.gpu.name} ({', '.join(p.gpu.encoders) or 'no encoders'})" if p.gpu else "no GPU"
        typer.secho(f"  {name}", fg=typer.colors.BRIGHT_WHITE)
        typer.echo(f"    {p.cores} threads / {p.physical_cores} cores · "
                   f"{p.ram_bytes // 2**30} GiB RAM · {p.disk_bytes // 2**30} GiB disk")
        typer.echo(f"    {gpu}")
        typer.echo(f"    idles at {p.cpu_mean:.0f}% CPU · relative speed ×{p.speed_factor}")
        typer.echo()

