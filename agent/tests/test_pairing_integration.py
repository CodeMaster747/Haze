"""Two real agents, two real identities, real TLS, real pairing.

Runs three agents as subprocesses on loopback. Not a unit test and not fast
(~15s), but it is the only test that exercises the thing the milestone is
actually about: two machines that have never met establishing mutual trust,
and refusing to when they should.

Every assertion here corresponds to a security property stated in SECURITY.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

STARTUP_TIMEOUT_S = 40.0
NODES = {
    # name:  (api port, node port)
    "alpha": (7533, 8543),
    "beta": (7534, 8544),
    "gamma": (7535, 8545),
}


class Node:
    """One agent subprocess, plus a client for its loopback API."""

    def __init__(self, name: str, home: Path, api_port: int, node_port: int) -> None:
        self.name = name
        self.home = home
        self.api_port = api_port
        self.node_port = node_port
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        env = {**os.environ, "HAZE_HOME": str(self.home)}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "haze", "up", "--no-open",
             "--port", str(self.api_port), "--node-port", str(self.node_port),
             "--name", self.name],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                out = self.process.stdout.read().decode() if self.process.stdout else ""
                raise RuntimeError(f"{self.name} exited during startup:\n{out}")
            try:
                self.get("/health")
                return
            except (urllib.error.URLError, OSError, FileNotFoundError):
                time.sleep(0.25)
        raise RuntimeError(f"{self.name} did not become ready within {STARTUP_TIMEOUT_S}s")

    def kill(self) -> None:
        """SIGKILL, with no chance to clean up -- the power-cut case, not a
        graceful shutdown."""
        if self.process is None:
            return
        self.process.kill()
        self.process.wait(timeout=10)
        self.process = None

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    # --- API ---------------------------------------------------------------

    @property
    def token(self) -> str:
        return str(json.loads((self.home / "config.json").read_text())["dashboard_token"])

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        origin = f"http://127.0.0.1:{self.api_port}"
        request = urllib.request.Request(
            f"{origin}/api/v1{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Origin": origin,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"null")

    def get(self, path: str) -> Any:
        return self.call("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.call("POST", path, body or {})

    # --- helpers -----------------------------------------------------------

    def pending(self, direction: str, timeout_s: float = 20.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for item in self.get("/pairing")["pending"]:
                if item["direction"] == direction:
                    return dict(item)
            time.sleep(0.2)
        return None

    def peers(self) -> list[dict[str, Any]]:
        return list(self.get("/peers")["peers"])

    def wait_for_peer_count(self, count: int, timeout_s: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if len(self.peers()) == count:
                return True
            time.sleep(0.2)
        return len(self.peers()) == count


@pytest.fixture(scope="module")
def cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Node]]:
    root = tmp_path_factory.mktemp("cluster")
    nodes = {
        name: Node(name, root / name, api_port, node_port)
        for name, (api_port, node_port) in NODES.items()
    }
    for node in nodes.values():
        node.start()
    try:
        yield nodes
    finally:
        for node in nodes.values():
            node.stop()


def test_nodes_have_distinct_identities(cluster: dict[str, Node]) -> None:
    ids = {name: node.get("/node")["node_id"] for name, node in cluster.items()}
    assert all(ids.values()), "every node must derive an identity on first run"
    assert len(set(ids.values())) == len(ids), f"identities collided: {ids}"


def test_pairing_shows_the_same_sas_on_both_screens(cluster: dict[str, Node]) -> None:
    """The milestone's demo moment, and the whole basis of the security model.

    A machine-in-the-middle would have to present a different public key on at
    least one leg, so the two screens could not agree.
    """
    alpha, beta = cluster["alpha"], cluster["beta"]
    alpha.post("/pairing/arm", {"ttl_s": 120})
    beta.post("/pairing/initiate", {"host": "127.0.0.1", "port": alpha.node_port})

    on_alpha = alpha.pending("incoming")
    on_beta = beta.pending("outgoing")
    assert on_alpha and on_beta, "both ends must show the request"

    assert on_alpha["sas_digits"] == on_beta["sas_digits"]
    assert on_alpha["sas_words"] == on_beta["sas_words"]
    assert len(on_alpha["sas_digits"]) == 6

    # Each side sees the *other* node named, never itself.
    assert on_alpha["name"] == "beta"
    assert on_beta["name"] == "alpha"

    alpha.post("/pairing/confirm", {"session_id": on_alpha["session_id"]})
    beta.post("/pairing/confirm", {"session_id": on_beta["session_id"]})

    assert alpha.wait_for_peer_count(1), "alpha should have paired"
    assert beta.wait_for_peer_count(1), "beta should have paired"


def test_each_side_learns_the_others_listening_port(cluster: dict[str, Node]) -> None:
    """Regression: the listening port must come from the handshake.

    An inbound connection's source port is ephemeral, so a node that only ever
    *receives* a connection cannot learn where to call back from the socket. An
    earlier version fell back to the local node port, which made a node ping
    itself and report success.
    """
    alpha, beta = cluster["alpha"], cluster["beta"]
    assert alpha.peers()[0]["last_port"] == beta.node_port
    assert beta.peers()[0]["last_port"] == alpha.node_port


def test_paired_nodes_can_reach_each_other(cluster: dict[str, Node]) -> None:
    alpha, beta = cluster["alpha"], cluster["beta"]
    assert alpha.post(f"/peers/{alpha.peers()[0]['node_id']}/ping")["ok"] is True
    assert beta.post(f"/peers/{beta.peers()[0]['node_id']}/ping")["ok"] is True


def test_successful_pairing_disarms_the_window(cluster: dict[str, Node]) -> None:
    """Leaving the window open would let a second, unnoticed device follow
    through the same opening."""
    assert cluster["alpha"].get("/pairing")["armed"] is False


def test_unarmed_node_refuses_a_stranger(cluster: dict[str, Node]) -> None:
    alpha, gamma = cluster["alpha"], cluster["gamma"]
    before = len(alpha.peers())

    gamma.post("/pairing/initiate", {"host": "127.0.0.1", "port": alpha.node_port})

    deadline = time.monotonic() + 15
    error = ""
    while time.monotonic() < deadline:
        error = str(gamma.get("/pairing").get("last_error") or "")
        if error:
            break
        time.sleep(0.2)

    assert "pair --serve" in error, f"expected an actionable refusal, got {error!r}"
    assert alpha.get("/pairing")["pending"] == [], "a stranger must not reach the user's screen"
    assert len(alpha.peers()) == before


def test_one_sided_decline_pairs_nobody(cluster: dict[str, Node]) -> None:
    """Both users must agree. If confirming alone were enough, a device on the
    LAN could pair itself while its owner was in another room."""
    alpha, gamma = cluster["alpha"], cluster["gamma"]
    before = len(alpha.peers())

    alpha.post("/pairing/arm", {"ttl_s": 60})
    gamma.post("/pairing/initiate", {"host": "127.0.0.1", "port": alpha.node_port})

    on_gamma = gamma.pending("outgoing")
    on_alpha = alpha.pending("incoming")
    assert on_gamma and on_alpha
    assert on_gamma["sas_digits"] == on_alpha["sas_digits"]

    gamma.post("/pairing/reject", {"session_id": on_gamma["session_id"]})
    alpha.post("/pairing/confirm", {"session_id": on_alpha["session_id"]})  # alpha says yes

    time.sleep(3)
    assert len(alpha.peers()) == before, "alpha confirmed, but gamma did not — nothing should pair"
    assert gamma.peers() == []
    alpha.post("/pairing/disarm")


def test_unpairing_revokes_access(cluster: dict[str, Node]) -> None:
    """Unpair is the revocation mechanism: the peer leaves the trust set and
    its next connection is refused at the handshake."""
    alpha, beta = cluster["alpha"], cluster["beta"]
    alpha_from_beta = beta.peers()[0]["node_id"]
    beta_from_alpha = alpha.peers()[0]["node_id"]

    beta.call("DELETE", f"/peers/{alpha_from_beta}")
    assert beta.peers() == []

    result = alpha.post(f"/peers/{beta_from_alpha}/ping")
    assert result["ok"] is False
    # Specifically "not paired" -- proving it reached beta and beta refused,
    # rather than failing to connect for some unrelated reason.
    assert "not paired" in str(result["detail"]).lower()


# --- fault injection --------------------------------------------------------
# What happens when a machine goes away mid-job is the difference between a
# distributed system and a demo. These assert the submitter finds out promptly
# and is told something it can act on.


def _pair(a: Node, b: Node) -> None:
    """Pair two nodes, confirming on both sides."""
    b.post("/pairing/arm", {"ttl_s": 120})
    a.post("/pairing/initiate", {"host": "127.0.0.1", "port": b.node_port})
    on_a, on_b = a.pending("outgoing"), b.pending("incoming")
    assert on_a and on_b
    a.post("/pairing/confirm", {"session_id": on_a["session_id"]})
    b.post("/pairing/confirm", {"session_id": on_b["session_id"]})
    assert a.wait_for_peer_count(1)


def test_a_worker_dying_mid_job_fails_fast_with_an_actionable_message(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Kill the machine running a job. The submitter must not hang, and must
    not be shown asyncio's "0 bytes read on a total of 4 expected bytes" --
    which was the real behaviour before this test existed.
    """
    root = tmp_path_factory.mktemp("chaos")
    submitter = Node("submitter", root / "submitter", 7601, 8601)
    worker = Node("worker", root / "worker", 7602, 8602)

    submitter.start()
    worker.start()
    try:
        _pair(submitter, worker)
        peer = submitter.peers()[0]

        job = submitter.post(
            "/jobs",
            {"runtime": "hashbench", "args": {"rounds": 6000}, "node_id": peer["node_id"],
             "label": "chaos victim", "cpu_cores": 1, "wall_seconds": 300},
        )
        job_id = job["job_id"]

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if submitter.get(f"/jobs/{job_id}")["state"] == "running":
                break
            time.sleep(0.2)
        else:
            pytest.fail("the job never started on the worker")

        worker.kill()

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = submitter.get(f"/jobs/{job_id}")
            if record["state"] in {"failed", "cancelled", "rejected"}:
                break
            time.sleep(0.25)
        else:
            pytest.fail("the submitter hung after its worker died")

        assert record["state"] == "failed"
        assert "disconnected" in record["error"]
        assert "resubmitting" in record["error"]
        # The raw asyncio wording must never reach a user.
        assert "expected bytes" not in record["error"]
    finally:
        submitter.stop()
        worker.stop()


def test_the_submitter_survives_its_worker_dying(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A peer disappearing must not take the local agent with it."""
    root = tmp_path_factory.mktemp("chaos2")
    submitter = Node("survivor", root / "survivor", 7603, 8603)
    worker = Node("doomed", root / "doomed", 7604, 8604)

    submitter.start()
    worker.start()
    try:
        _pair(submitter, worker)
        worker.kill()
        time.sleep(2)

        # Still serving, still able to run work locally.
        assert submitter.get("/health")["ok"] is True
        local = submitter.post(
            "/jobs", {"runtime": "hashbench", "args": {"rounds": 10}, "cpu_cores": 1,
                      "wall_seconds": 60},
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = submitter.get(f"/jobs/{local['job_id']}")
            if record["state"] != "running":
                break
            time.sleep(0.2)
        assert record["state"] == "succeeded"
    finally:
        submitter.stop()
        worker.stop()
