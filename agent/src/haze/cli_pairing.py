"""`haze pair`, `haze peers`, `haze unpair`, `haze id`.

All of these drive the running agent through its loopback API rather than
touching the database directly, so the agent stays the single writer.

The pairing UX is deliberately symmetric: whichever machine you are standing in
front of, you see the same six digits and the same question. That symmetry is
the security property -- if one side could confirm on behalf of the other, a
device on your network could pair itself while you were in another room.
"""

from __future__ import annotations

import ipaddress
import time
from typing import Any

import typer

from haze import apiclient, config, log
from haze.identity import keys, nodeid

pair_app = typer.Typer(help="Pair this machine with another Haze node.")

POLL_INTERVAL_S = 0.4


def _hostport(host: str, port: int) -> str:
    """Render an address the way it would be typed back in.

    A bare IPv6 literal needs brackets or `::1:8443` is unreadable -- the
    colons run together and there is no telling where the address ends.
    """
    try:
        bracket = ipaddress.ip_address(host.split("%")[0]).version == 6
    except ValueError:
        bracket = False
    return f"[{host}]:{port}" if bracket else f"{host}:{port}"


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
    for address, label in _address_hints():
        suffix = f"   ({label})" if label else ""
        typer.echo(f"  On the other machine run:  haze pair --host {address}{suffix}")
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


# Tailscale allocates from the RFC 6598 shared range. Recognising it is only
# used to offer the address in a hint; nothing depends on being right.
_OVERLAY_V4 = ipaddress.ip_network("100.64.0.0/10")


def _default_route_address() -> str:
    """The local address the routing table would use to reach the internet.

    Best effort: connects a UDP socket to a public address to learn which local
    interface would be chosen. Nothing is sent -- connect() on a datagram
    socket only sets the default destination.
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed unroutable
            return str(s.getsockname()[0])
    except OSError:
        return ""


def _overlay_address() -> str:
    """This machine's overlay address, if it is on one.

    The default route is the wrong answer on a machine whose peers are reached
    over Tailscale: it names the LAN interface, and printing it tells the user
    to type an address the other machine cannot reach. psutil is already a
    dependency and enumerates interfaces on all three platforms, which parsing
    `ip` or `ifconfig` output does not.
    """
    import psutil

    for addresses in psutil.net_if_addrs().values():
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address.address.split("%")[0])
            except (ValueError, AttributeError):
                continue
            if parsed.version == 4 and parsed in _OVERLAY_V4:
                return str(parsed)
    return ""


def _address_hints() -> list[tuple[str, str]]:
    """Addresses to offer the other machine, each with a label.

    Both are offered when both exist rather than guessing: only the user knows
    whether the other machine is on this network.
    """
    hints = []
    lan = _default_route_address()
    overlay = _overlay_address()
    if lan and lan != overlay:
        hints.append((lan, "on this network"))
    if overlay:
        hints.append((overlay, "if it is not on this network"))
    if not hints:
        hints.append(("<this machine's address>", ""))
    return hints


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
        if peer.get("pinned_host"):
            typer.secho(
                f"           pinned    {_hostport(peer['pinned_host'], peer['pinned_port'])}",
                fg=typer.colors.CYAN,
            )
        typer.echo()


def _resolve_peer(identifier: str) -> str:
    """Turn what a user typed into a canonical node id.

    Accepts whatever `haze peers` displays -- the short id or the display name
    -- so peer commands take the same identifiers as `haze run --on`. Anything
    a user can read off the screen should work in the command that acts on it.

    Refuses to guess when a display name matches two machines. `haze run --on`
    takes the first match, which is fine for placing a job and wrong for
    anything that changes a peer: unpairing or misdirecting the address of the
    machine the user did not mean is not something they can undo remotely.
    """
    if len(identifier.replace("-", "")) == 56:
        return nodeid.normalise(identifier)

    peers = apiclient.get("/peers")["peers"]
    target = identifier.strip().upper()
    matches = [p for p in peers if target in {p["short_id"].upper(), p["name"].upper()}]

    if not matches:
        known = ", ".join(f"{p['name']} ({p['short_id']})" for p in peers) or "none paired"
        _fail(f"  no paired peer matching {identifier!r}. Known: {known}")
    if len(matches) > 1:
        names = ", ".join(f"{p['name']} ({p['short_id']})" for p in matches)
        _fail(f"  {identifier!r} matches {len(matches)} peers: {names}.\n"
              f"  Use the short id to say which one.")
    return str(matches[0]["node_id"])


def unpair_command(node_id: str) -> None:
    """Remove a paired node. Its next connection is refused at the handshake."""
    log.setup()
    try:
        canonical = _resolve_peer(node_id)
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


# --- addresses ---------------------------------------------------------------

def address_command(
    peer: str = typer.Argument(..., help="Short id or name, as `haze peers` shows it."),
    set_: str = typer.Option("", "--set", help="Address to pin for this peer."),
    port: int = typer.Option(0, "--port", help="Its node port (default 8443)."),
    clear: bool = typer.Option(False, "--clear", help="Forget the pinned address."),
) -> None:
    """Show, pin, or clear the address used to reach a peer.

    Haze records where a peer last connected from, and overwrites it on every
    inbound session. A machine reachable both on the LAN and over an overlay
    network therefore flips between the two. Pinning an address settles it:
    observed traffic no longer overwrites it, and it is tried first.

    The address is taken as a bare host with a separate --port rather than a
    `host:port` string, so an IPv6 literal needs no brackets and no escaping.
    """
    log.setup()
    if set_ and clear:
        _fail("  give either --set <address> or --clear, not both.")

    try:
        node_id = _resolve_peer(peer)

        if clear:
            apiclient.delete(f"/peers/{node_id}/address")
            typer.secho(f"\n  cleared the pinned address for {peer}\n", fg=typer.colors.YELLOW)
            return

        if set_:
            result = apiclient.put(
                f"/peers/{node_id}/address", {"host": set_.strip(), "port": port}
            )
            typer.secho(f"\n  pinned {peer} at {_hostport(result['host'], result['port'])}\n",
                        fg=typer.colors.GREEN, bold=True)
            return

        _show_addresses(node_id)
    except apiclient.AgentNotRunningError as exc:
        _fail(str(exc))
    except apiclient.ApiError as exc:
        _fail(f"  {exc}")


def _show_addresses(node_id: str) -> None:
    """Print what is known about how to reach one peer, in dial order."""
    match = next(
        (p for p in apiclient.get("/peers")["peers"] if p["node_id"] == node_id), None
    )
    if match is None:  # pragma: no cover - resolved a moment ago
        _fail("  that peer is no longer paired.")
        return

    typer.echo()
    typer.secho(f"  {match['short_id']}  {match['name']}", fg=typer.colors.GREEN)
    if match.get("pinned_host"):
        typer.secho(f"    pinned      {_hostport(match['pinned_host'], match['pinned_port'])}",
                    fg=typer.colors.CYAN)
    else:
        typer.secho("    pinned      none", fg=typer.colors.BRIGHT_BLACK)
    if match["last_host"]:
        typer.echo(f"    last seen   {_hostport(match['last_host'], match['last_port'])}")
    else:
        typer.secho("    last seen   never", fg=typer.colors.BRIGHT_BLACK)

    if not match.get("pinned_host") and not match["last_host"]:
        typer.secho("\n    Nothing to dial. Pin an address with "
                    "`haze address <peer> --set <host>`.", fg=typer.colors.YELLOW)
    typer.echo()
