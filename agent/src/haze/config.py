"""Agent configuration and on-disk state layout.

Everything Haze persists lives under one directory (default ``~/.haze``) so that
"how do I completely reset this?" has a one-line answer: delete it.

Two files matter for security:

* ``config.json`` (mode 0600) holds the dashboard bearer token.  Any process
  that can read it can drive this machine's compute, so the permission check in
  :func:`_read_secure_json` is enforcement, not hygiene.
* ``identity.key`` (mode 0600, written in M1) holds the Ed25519 seed.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haze import log

_log = log.get("config")

# The dashboard port.  Chosen to avoid the well-known local-agent ports a Haze
# user plausibly already runs: 8384 (Syncthing), 8123 (Home Assistant), 8096
# (Jellyfin), 11434 (Ollama), 1234 (LM Studio), 47990 (Sunshine).
DEFAULT_API_PORT = 7433
API_PORT_SCAN = 10          # try 7433..7442 before giving up

# Node-to-node mutual-TLS listener (M1).  Separate process-wide port because it
# is a raw asyncio TLS server, not uvicorn -- uvicorn cannot expose the peer
# certificate to the app, and peer certs *are* our identity.
DEFAULT_NODE_PORT = 8443

# UDP broadcast discovery beacon (M2).  Fallback for when mDNS is eaten by
# IGMP snooping or a mesh AP.
DEFAULT_BEACON_PORT = 47654


def state_dir() -> Path:
    """Root of Haze's on-disk state.  ``HAZE_HOME`` overrides it, which is what
    ``haze devnet`` uses to run N isolated agents on one machine."""
    raw = os.environ.get("HAZE_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".haze"


def ensure_state_dir() -> Path:
    d = state_dir()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkdir's mode is ignored if the directory already exists, so fix it up.
    if stat.S_IMODE(d.stat().st_mode) != 0o700:
        d.chmod(0o700)
    return d


def _write_secure_json(path: Path, payload: dict[str, Any]) -> None:
    """Write 0600 JSON atomically.

    O_EXCL on a temp file then os.replace: a reader never observes a
    half-written token, and the file is never briefly world-readable the way
    ``open(path, "w")`` followed by ``chmod`` would leave it.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def _read_secure_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        # Refuse rather than repair.  A group- or world-readable token file
        # means the token should be considered leaked, and silently chmod-ing it
        # would hide that from the user.
        raise PermissionError(
            f"{path} is mode {mode:04o}; it must not be readable by group or others. "
            f"Delete it and restart the agent to mint a fresh token."
        )
    with path.open() as fh:
        data: dict[str, Any] = json.load(fh)
    return data


@dataclass(frozen=True)
class Config:
    """Resolved agent configuration."""

    node_name: str
    api_port: int
    node_port: int
    beacon_port: int
    dashboard_token: str
    """Bearer token required on every /api call and on the /ws upgrade.

    Not a nicety.  The agent's loopback API can execute subprocesses, so an
    unauthenticated loopback server is remote code execution for any web page
    the user happens to open -- exactly the "Local Mess" class of bug that
    motivated Chrome's Local Network Access work.
    """

    @property
    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}/?t={self.dashboard_token}"


def load_or_create(
    node_name: str | None = None,
    api_port: int | None = None,
    node_port: int | None = None,
) -> Config:
    """Read ``config.json``, creating it (and a fresh token) on first run."""
    d = ensure_state_dir()
    path = d / "config.json"

    data = _read_secure_json(path) or {}
    changed = False

    if "dashboard_token" not in data:
        # 32 bytes -> 43 url-safe chars.  Regenerated only by deleting the file.
        data["dashboard_token"] = secrets.token_urlsafe(32)
        changed = True

    # An explicitly given --name is persisted, so `haze id` and `haze peers`
    # agree with what `haze up --name` displayed. Without this the flag applied
    # only to the running process and every other command showed the hostname.
    if node_name and data.get("node_name") != node_name:
        data["node_name"] = node_name
        changed = True
    elif "node_name" not in data:
        data["node_name"] = socket.gethostname().split(".")[0] or "haze-node"
        changed = True

    # Same for --node-port: other machines are told this value during the
    # handshake, so it has to survive a restart or they would call back to a
    # port nothing is listening on.
    if node_port and data.get("node_port") != node_port:
        data["node_port"] = node_port
        changed = True

    for key, default in (
        ("api_port", DEFAULT_API_PORT),
        ("node_port", DEFAULT_NODE_PORT),
        ("beacon_port", DEFAULT_BEACON_PORT),
    ):
        if key not in data:
            data[key] = default
            changed = True

    if changed:
        _write_secure_json(path, data)
        _log.debug("wrote %s", path)

    # HAZE_BEACON_PORT lets `haze devnet` put its agents on their own
    # discovery channel, so a devnet and a real agent on the same machine
    # do not find each other and confuse the peer list.
    beacon = int(os.environ.get("HAZE_BEACON_PORT") or data["beacon_port"])

    return Config(
        node_name=str(node_name or data["node_name"]),
        api_port=int(api_port or data["api_port"]),
        node_port=int(node_port or data["node_port"]),
        beacon_port=beacon,
        dashboard_token=str(data["dashboard_token"]),
    )


# --- runtime handoff --------------------------------------------------------
# `haze up` writes where it actually landed; `haze open`/`haze status` read it.
# Needed because the API port is scanned, so the running port is not knowable
# from config alone.

def runtime_path() -> Path:
    return state_dir() / "agent.json"


def write_runtime(cfg: Config, api_port: int) -> None:
    _write_secure_json(
        runtime_path(),
        {"pid": os.getpid(), "api_port": api_port, "node_name": cfg.node_name,
         "url": f"http://127.0.0.1:{api_port}/?t={cfg.dashboard_token}"},
    )


def read_runtime() -> dict[str, Any] | None:
    try:
        return _read_secure_json(runtime_path())
    except (PermissionError, json.JSONDecodeError):
        return None


def clear_runtime() -> None:
    runtime_path().unlink(missing_ok=True)


def find_free_port(start: int, span: int = API_PORT_SCAN) -> int:
    """First bindable port in ``[start, start+span)`` on 127.0.0.1.

    Binds to the literal 127.0.0.1 rather than 0.0.0.0 so the probe matches what
    the server will actually do -- a port free on loopback may be taken on a
    LAN interface and vice versa.
    """
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"no free port in {start}-{start + span - 1}; is another Haze agent already running? "
        f"Try `haze status`."
    )
