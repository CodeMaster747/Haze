"""`haze pair`, `haze peers`, `haze unpair`, `haze id`.

All of these drive the running agent through its loopback API rather than
touching the database directly, so the agent stays the single writer.

The pairing UX is deliberately symmetric: whichever machine you are standing in
front of, you see the same six digits and the same question. That symmetry is
the security property -- if one side could confirm on behalf of the other, a
device on your network could pair itself while you were in another room.
"""

from __future__ import annotations

import time
from typing import Any

import typer

from haze import apiclient, config, log
from haze.identity import keys, nodeid

pair_app = typer.Typer(help="Pair this machine with another Haze node.")

POLL_INTERVAL_S = 0.4


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


def _show_sas(pending: dict[str, Any], role: str) -> None:
    digits = str(pending["sas_digits"])
    words = " · ".join(str(w) for w in pending["sas_words"])
    name = pending["name"]
    short = pending["short_id"]

    typer.echo()
    typer.secho(f"  {role} {name}  ({short})", fg=typer.colors.BRIGHT_WHITE)
    typer.echo(f"  {pending.get('platform') or 'unknown platform'}")
    typer.echo()
    typer.secho(f"      {'  '.join(digits)}", fg=typer.colors.BRIGHT_MAGENTA, bold=True)
    typer.secho(f"      {words}", fg=typer.colors.MAGENTA)
    typer.echo()
    typer.secho(
        "  These exact digits must also be showing on the other machine.",
        fg=typer.colors.YELLOW,
    )
    typer.secho(
        "  If they differ, something is intercepting the connection -- answer no.",
        fg=typer.colors.YELLOW,
    )
    typer.echo()


def _await_pending(direction: str, timeout_s: float) -> dict[str, Any] | None:
    """Poll the agent until a pairing request in ``direction`` appears."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = apiclient.get("/pairing")
        error = state.get("last_error")
        if error:
            _fail(f"  {error}")
        for pending in state.get("pending", []):
            if pending["direction"] == direction:
                return dict(pending)
        time.sleep(POLL_INTERVAL_S)
    return None


def _decide(session_id: str) -> bool:
    confirmed = typer.confirm("  Do both machines show the same digits?", default=False)
    apiclient.post("/pairing/confirm" if confirmed else "/pairing/reject",
                   {"session_id": session_id})
    return confirmed


@pair_app.callback(invoke_without_command=True)
def pair(
    host: str = typer.Option("", "--host", "-h", help="Address of the node to pair with."),
    port: int = typer.Option(0, "--port", "-p", help="Its node port (default 8443)."),
    serve: bool = typer.Option(False, "--serve", "-s", help="Wait for another node to pair with this one."),
    ttl: float = typer.Option(180.0, "--ttl", help="Seconds to stay open for, with --serve."),
) -> None:
    """Pair with another Haze node.

    On one machine:   haze pair --serve
    On the other:     haze pair --host <address of the first>
    """
    log.setup()
    if serve == bool(host):
        _fail("give either --serve (to wait) or --host <address> (to initiate), not both or neither.")

    try:
        if serve:
            _serve_pairing(ttl)
        else:
            _initiate_pairing(host, port)
    except apiclient.AgentNotRunningError as exc:
        _fail(f"{exc}")
    except apiclient.ApiError as exc:
        _fail(f"agent refused the request -- {exc}")


def _serve_pairing(ttl: float) -> None:
    apiclient.post("/pairing/arm", {"ttl_s": ttl})
    me = apiclient.get("/node")
    typer.echo()
    typer.secho(f"  Waiting for a node to pair with {me['name']} ({me['short_id']})",
                fg=typer.colors.BRIGHT_WHITE)
    typer.echo(f"  On the other machine run:  haze pair --host {_best_lan_hint()}")
    typer.secho(f"  Open for {ttl:.0f}s. Ctrl-C to stop.", fg=typer.colors.BRIGHT_BLACK)

    pending = _await_pending("incoming", ttl)
    if pending is None:
        _fail("  nobody connected before the window closed.")
        return

    _show_sas(pending, "Pairing request from")
    if not _decide(str(pending["session_id"])):
        typer.secho("  Declined. Nothing was paired.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    _report_result(str(pending["node_id"]), str(pending["name"]))


def _initiate_pairing(host: str, port: int) -> None:
    apiclient.post("/pairing/initiate", {"host": host, "port": port})
    typer.secho(f"\n  Connecting to {host}...", fg=typer.colors.BRIGHT_BLACK)

    pending = _await_pending("outgoing", 30.0)
    if pending is None:
        _fail(f"  {host} did not respond. Is `haze pair --serve` running there?")
        return

    _show_sas(pending, "Pairing with")
    if not _decide(str(pending["session_id"])):
        typer.secho("  Declined. Nothing was paired.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.secho("  Waiting for the other machine to confirm...", fg=typer.colors.BRIGHT_BLACK)
    _report_result(str(pending["node_id"]), str(pending["name"]))


def _report_result(node_id: str, name: str) -> None:
    """Poll the peer list until the pairing lands, or the other side declines."""
    deadline = time.monotonic() + 150.0
    while time.monotonic() < deadline:
        for peer in apiclient.get("/peers")["peers"]:
            if peer["node_id"] == node_id:
                typer.secho(f"\n  Paired with {name} ({peer['short_id']})\n",
                            fg=typer.colors.GREEN, bold=True)
                return
        state = apiclient.get("/pairing")
        if state.get("last_error"):
            _fail(f"  {state['last_error']}")
        time.sleep(POLL_INTERVAL_S)
    _fail("  the other machine did not confirm in time.")


def _best_lan_hint() -> str:
    """A LAN address to print in the instructions.

    Best effort: connects a UDP socket to a public address to learn which local
    interface the routing table would use. Nothing is sent -- connect() on a
    datagram socket only sets the default destination.
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed unroutable
            return str(s.getsockname()[0])
    except OSError:
        return "<this machine's LAN address>"


# --- peers ------------------------------------------------------------------

def peers_command() -> None:
    """List paired nodes."""
    log.setup()
    try:
        data = apiclient.get("/peers")
    except apiclient.AgentNotRunningError as exc:
        _fail(str(exc))
        return

    me = data["self"]
    typer.secho(f"\n  this node  {me['name']}  {me['node_id']}\n", fg=typer.colors.BRIGHT_WHITE)

    if not data["peers"]:
        typer.secho("  no paired peers yet -- run `haze pair --serve` on one machine "
                    "and `haze pair --host <address>` on the other.\n",
                    fg=typer.colors.BRIGHT_BLACK)
        return

    for peer in data["peers"]:
        seen = peer["last_seen_at"] or "never"
        typer.secho(f"  {peer['short_id']}  {peer['name']}", fg=typer.colors.GREEN)
        typer.echo(f"           {peer['node_id']}")
        typer.echo(f"           {peer['platform'] or 'unknown'} · haze {peer['version'] or '?'}")
        typer.echo(f"           last seen {seen}  at {peer['last_host'] or '?'}")
        typer.echo()


def unpair_command(node_id: str) -> None:
    """Remove a paired node. Its next connection is refused at the handshake."""
    log.setup()
    try:
        canonical = nodeid.normalise(node_id) if len(node_id.replace("-", "")) == 56 else None
        if canonical is None:
            # Allow the short form shown in `haze peers`.
            matches = [
                p for p in apiclient.get("/peers")["peers"]
                if p["short_id"].upper() == node_id.strip().upper()
            ]
            if not matches:
                _fail(f"  no paired peer matching {node_id!r}")
                return
            canonical = matches[0]["node_id"]

        apiclient.delete(f"/peers/{canonical}")
        typer.secho(f"  unpaired {nodeid.short(canonical)}", fg=typer.colors.YELLOW)
    except apiclient.AgentNotRunningError as exc:
        _fail(str(exc))
    except apiclient.ApiError as exc:
        _fail(f"  {exc}")


def id_command() -> None:
    """Show this node's identity. Works without a running agent."""
    log.setup()
    cfg = config.load_or_create()
    identity = keys.load_or_create()
    typer.echo()
    typer.secho(f"  {cfg.node_name}", fg=typer.colors.BRIGHT_WHITE, bold=True)
    typer.secho(f"  {identity.node_id}", fg=typer.colors.BRIGHT_MAGENTA)
    typer.echo(f"  short  {identity.short_id}")
    typer.echo(f"  key    {config.state_dir() / keys.KEY_FILENAME}")
    typer.echo()
