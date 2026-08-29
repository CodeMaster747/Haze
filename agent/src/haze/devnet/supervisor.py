"""`haze devnet` -- N agents with synthetic hardware, on one machine.

Why a plain process supervisor rather than docker-compose
---------------------------------------------------------
The obvious instinct is `docker compose up --scale node=4`, and it does not
work. Compose V2 broke the V1 behaviour where ``deploy.replicas`` plus a
published port *range* assigned one host port per replica; V2 tries to bind the
whole range for every replica and the second container fails with "port is
already allocated" (docker/compose #8530, #8878, #10246, still open).

Two more reasons specific to this machine: Docker Desktop for Mac has no GPU
passthrough at all, so a "GPU node" in a container would be fake regardless of
the profile; and ``--network=host`` does not behave like Linux host networking
there, which breaks the multicast discovery this is meant to exercise.

So: N subprocesses, explicit distinct ports, one state directory each.

Discovery is left ON. Running four agents that genuinely find each other over
UDP broadcast on loopback is the point -- it exercises the real code path
rather than a fixture, and it is how you find out your discovery layer cannot
tell two agents apart when they share an IP. (It keys on node ID, so it can.)
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from haze import config, log
from haze.probe import synthetic

_log = log.get("devnet")

# Deliberately clear of the default single-agent ports (7433 / 8443) so a
# devnet can run alongside a real agent without either noticing.
BASE_API_PORT = 7801
BASE_NODE_PORT = 8801
# A separate beacon port too, so devnet agents discover each other and not the
# real agent on this machine.
BEACON_PORT = 47655

DEFAULT_PROFILES = ("workstation", "laptop", "nas", "builder")


@dataclass
class DevNode:
    name: str
    profile: str
    home: Path
    api_port: int
    node_port: int
    process: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}/"

    def token(self) -> str | None:
        path = self.home / "config.json"
        if not path.is_file():
            return None
        with contextlib.suppress(json.JSONDecodeError, OSError, KeyError):
            return str(json.loads(path.read_text())["dashboard_token"])
        return None

    @property
    def console_url(self) -> str:
        token = self.token()
        return f"{self.url}?t={token}" if token else self.url


def plan(count: int, profiles: list[str] | None = None) -> list[DevNode]:
    """Lay out ``count`` nodes without starting anything."""
    available = synthetic.available()
    chosen = profiles or list(DEFAULT_PROFILES)
    for name in chosen:
        if name not in available:
            raise ValueError(f"unknown profile {name!r}; available: {', '.join(available)}")

    root = config.state_dir().parent / ".haze-devnet"
    nodes: list[DevNode] = []
    for index in range(count):
        # Cycle the profile list when asked for more nodes than profiles, so
        # `-n 8` gives two of each rather than failing.
        profile = chosen[index % len(chosen)]
        suffix = "" if index < len(chosen) else f"-{index // len(chosen) + 1}"
        name = f"{profile}{suffix}"
        nodes.append(
            DevNode(
                name=name,
                profile=profile,
                home=root / name,
                api_port=BASE_API_PORT + index,
                node_port=BASE_NODE_PORT + index,
            )
        )
    return nodes


class DevNet:
    """Starts and stops a set of agents."""

    def __init__(self, nodes: list[DevNode]) -> None:
        self._nodes = nodes

    @property
    def nodes(self) -> list[DevNode]:
        return self._nodes

    def start(self) -> None:
        for node in self._nodes:
            node.home.mkdir(mode=0o700, parents=True, exist_ok=True)
            env = {
                **os.environ,
                "HAZE_HOME": str(node.home),
                # Every devnet agent shares a beacon port so they find each
                # other, and it differs from the default so they do not gatecrash
                # a real agent's network.
                "HAZE_BEACON_PORT": str(BEACON_PORT),
            }
            node.process = subprocess.Popen(  # noqa: S603 -- fixed argv, our own module
                [
                    sys.executable, "-m", "haze", "up", "--no-open",
                    "--port", str(node.api_port),
                    "--node-port", str(node.node_port),
                    "--name", node.name,
                    "--profile", node.profile,
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _log.debug("started %s on %d", node.name, node.api_port)

    def wait_ready(self, timeout_s: float = 40.0) -> list[DevNode]:
        """Block until every node answers, or the deadline passes.

        Returns whichever nodes came up, so a partial devnet is usable and the
        caller can say which ones failed rather than aborting the lot.
        """
        import urllib.error
        import urllib.request

        deadline = time.monotonic() + timeout_s
        ready: list[DevNode] = []
        while time.monotonic() < deadline and len(ready) < len(self._nodes):
            for node in self._nodes:
                if node in ready:
                    continue
                token = node.token()
                if token is None:
                    continue
                try:
                    request = urllib.request.Request(  # noqa: S310 -- fixed loopback URL
                        f"{node.url}api/v1/health",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    with urllib.request.urlopen(request, timeout=2):  # noqa: S310
                        ready.append(node)
                except (urllib.error.URLError, OSError):
                    pass
            if len(ready) < len(self._nodes):
                time.sleep(0.3)
        return ready

    def stop(self) -> None:
        for node in self._nodes:
            if node.process is None:
                continue
            with contextlib.suppress(ProcessLookupError):
                node.process.send_signal(signal.SIGTERM)
        for node in self._nodes:
            if node.process is None:
                continue
            try:
                node.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                node.process.kill()
                node.process.wait(timeout=5)
        _log.info("devnet stopped")
