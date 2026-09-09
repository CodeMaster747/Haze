"""`haze autostart` -- start Haze at login on Windows, and stop it.

The off switch gets the same billing as the on switch everywhere in here: it is
printed by `enable` at the moment someone turns it on, written into the batch
file itself as a comment, and reported by `status`.  Someone lending you their
gaming PC should never have to search for how to stop lending it.
"""

from __future__ import annotations

import os
import sys

import typer

from haze import autostart, log

autostart_app = typer.Typer(
    help="Start Haze automatically when you log in (Windows).",
    no_args_is_help=True,
)


def _fail(msg: str) -> None:
    typer.secho(f"\n{msg}\n", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _require_windows() -> None:
    """Windows only, and say what to do everywhere else rather than just no.

    `os.name` rather than `sys.platform`, matching `config.ENFORCES_FILE_MODES`
    -- and unlike `sys.platform` it is not narrowed by mypy, so the code below
    stays type-checked on every platform instead of being written off as
    unreachable.
    """
    if os.name == "nt":
        return
    _fail(
        "  `haze autostart` configures the Windows Startup folder, and this is\n"
        f"  {sys.platform}.\n\n"
        "  On macOS, run Haze at login with a launchd agent; on Linux, with\n"
        "  `systemd --user`.  Both want the same command:\n\n"
        "      haze up --no-open"
    )


@autostart_app.command("enable")
def enable() -> None:
    """Start Haze minimised whenever you log in to Windows."""
    log.setup()
    _require_windows()
    try:
        written = autostart.enable(os.environ, autostart.haze_executable())
    except autostart.AutostartError as exc:
        _fail(str(exc))
        return

    typer.echo()
    typer.secho("  Haze will now start when you log in.", fg=typer.colors.GREEN)
    typer.echo()
    for path in written:
        typer.secho(f"  {path}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo()
    typer.echo("  Open the dashboard any time from the Start menu: type “Haze Console”.")
    typer.echo("  To stop Haze starting with Windows:")
    typer.secho("      haze autostart disable", fg=typer.colors.BRIGHT_WHITE)
    typer.echo("  or delete the files above — press Win+R and type `shell:startup`.")
    typer.echo()


@autostart_app.command("disable")
def disable() -> None:
    """Stop Haze starting when you log in, and remove the Start menu entry."""
    log.setup()
    _require_windows()
    try:
        removed, foreign = autostart.disable(os.environ)
    except autostart.AutostartError as exc:
        _fail(str(exc))
        return

    typer.echo()
    if not removed and not foreign:
        # Not an error.  Someone checking whether they already turned it off
        # deserves an answer, not an exit code.
        typer.secho("  Haze was not set to start at login. Nothing to remove.",
                    fg=typer.colors.YELLOW)
    for path in removed:
        typer.secho(f"  removed  {path}", fg=typer.colors.YELLOW)
    for path in foreign:
        typer.secho(f"  left alone  {path}", fg=typer.colors.YELLOW)
        typer.echo("      Haze did not write this file, so it is not ours to delete.")
    if removed:
        typer.echo()
        typer.echo("  Haze will no longer start at login. To start it now: `haze up`.")
    typer.echo()


@autostart_app.command("status")
def status() -> None:
    """Show whether Haze is set to start at login, and from where."""
    log.setup()
    _require_windows()
    try:
        entries = autostart.status(os.environ)
    except autostart.AutostartError as exc:
        _fail(str(exc))
        return

    on = any(present for _, present in entries)
    typer.echo()
    if on:
        typer.secho("  Haze starts at login.", fg=typer.colors.GREEN)
    else:
        typer.secho("  Haze does not start at login.", fg=typer.colors.YELLOW)
    typer.echo()
    for path, present in entries:
        mark = "present" if present else "absent "
        typer.secho(f"  {mark}  {path}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo()
    typer.echo("  To stop this:" if on else "  To turn it on:")
    typer.secho(f"      haze autostart {'disable' if on else 'enable'}",
                fg=typer.colors.BRIGHT_WHITE)
    typer.echo()
