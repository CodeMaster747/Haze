"""The `haze` command.

Distribution is `haze-agent` on PyPI; the console script is `haze`.
"""

from __future__ import annotations

import asyncio
import os
import sys
import webbrowser

import typer

import haze
from haze import cli_devnet, cli_jobs, cli_pairing, config, log

app = typer.Typer(
    name="haze",
    help="Pool your own machines into a private compute network.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def up(
    port: int = typer.Option(0, "--port", "-p", help="Dashboard port (default: 7433, scanning up)."),
    node_port: int = typer.Option(0, "--node-port", help="Port other nodes connect to (default: 8443)."),
    name: str = typer.Option("", "--name", "-n", help="Display name for this node."),
    profile: str = typer.Option(
        "", "--profile",
        help="Report synthetic hardware from this profile instead of the real machine. "
             "Nodes started this way are badged SIMULATED everywhere.",
    ),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the dashboard."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the node agent and serve the dashboard on 127.0.0.1."""
    log.setup(verbose)
    cfg = config.load_or_create(node_name=name or None, api_port=port or None,
                                node_port=node_port or None)

    try:
        actual_port = config.find_free_port(cfg.api_port)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if actual_port != cfg.api_port:
        typer.secho(f"port {cfg.api_port} busy, using {actual_port}", fg=typer.colors.YELLOW, err=True)

    url = f"http://127.0.0.1:{actual_port}/?t={cfg.dashboard_token}"
    config.write_runtime(cfg, actual_port)

    from haze.identity.keys import load_or_create as _load_identity

    identity = _load_identity()
    typer.secho(f"\n  Haze {haze.__version__}  ·  {cfg.node_name}  ({identity.short_id})",
                fg=typer.colors.BRIGHT_WHITE)
    typer.secho(f"  Peers:   0.0.0.0:{cfg.node_port}", fg=typer.colors.BRIGHT_BLACK)
    if profile:
        typer.secho(f"  SIMULATED hardware — profile “{profile}”", fg=typer.colors.MAGENTA)
    typer.secho(f"  Console: {url}\n", fg=typer.colors.BRIGHT_MAGENTA)

    if open_browser:
        # Best-effort. Headless boxes (the NAS case) have no browser and
        # webbrowser.open just returns False; the URL above is still printed.
        webbrowser.open(url)

    from haze.api.app import serve

    try:
        asyncio.run(serve(cfg, actual_port, profile=profile or None))
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    finally:
        config.clear_runtime()


@app.command()
def status() -> None:
    """Show whether an agent is running on this machine, and where."""
    log.setup()
    rt = config.read_runtime()
    if rt is None:
        typer.secho("no agent running (no ~/.haze/agent.json)", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    pid = int(rt.get("pid", 0))
    alive = _pid_alive(pid)
    if not alive:
        # A stale file after a crash or a kill -9.  Say so plainly rather than
        # printing a URL that will not load.
        typer.secho(f"stale runtime file: pid {pid} is gone. Run `haze up`.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.secho(f"running  pid={pid}  node={rt.get('node_name')}", fg=typer.colors.GREEN)
    typer.echo(str(rt.get("url", "")))


@app.command("open")
def open_console() -> None:
    """Open the dashboard for the running agent."""
    log.setup()
    rt = config.read_runtime()
    if rt is None or not _pid_alive(int(rt.get("pid", 0))):
        typer.secho("no agent running -- start one with `haze up`", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    webbrowser.open(str(rt["url"]))


app.add_typer(cli_pairing.pair_app, name="pair")
app.add_typer(cli_devnet.devnet_app, name="devnet")
app.command("run")(cli_jobs.run_command)
app.command("jobs")(cli_jobs.jobs_command)
app.command("bench")(cli_jobs.bench_command)
app.command("explain")(cli_jobs.explain_command)
app.command("peers")(cli_pairing.peers_command)
app.command("unpair")(cli_pairing.unpair_command)
app.command("id")(cli_pairing.id_command)


@app.command()
def version() -> None:
    """Print version information."""
    typer.echo(f"haze {haze.__version__} (protocol v{haze.PROTOCOL_VERSION})")
    typer.echo(f"python {sys.version.split()[0]}  ·  state {config.state_dir()}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)   # signal 0 tests existence without touching the process
    except ProcessLookupError:
        return False
    except PermissionError:
        return True       # exists, owned by someone else
    return True


def main() -> None:
    """Entry point.

    Turns the recoverable on-disk conditions -- a corrupt config, a truncated
    key, a key someone has chmod'd open -- into a message and an exit code.
    Each of those already carries a precise explanation and a remedy, and
    burying it under forty lines of traceback both hides the remedy and makes a
    fixable situation look like a crash.

    Set HAZE_DEBUG=1 to get the traceback back.
    """
    try:
        app()
    except (config.HazeConfigError, PermissionError, ValueError) as exc:
        if os.environ.get("HAZE_DEBUG"):
            raise
        typer.secho(f"\n{exc}\n", fg=typer.colors.RED, err=True)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
