"""`placement: "auto"` -- the submit path actually asking the scheduler.

The scheduler itself is tested in test_scheduler.py, against a golden corpus.
What is tested here is the *wiring*: that a submission gathers the two inputs
`decide` needs and nobody else has (the input byte total, and a work estimate),
that the node it names is turned back into the right one of the two branches
POST /jobs already had, and that a decision to place nothing is delivered in
the same shape as every other refusal rather than as a special case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from haze.api import routes_jobs
from haze.jobs.runtimes.hashbench import SECONDS_PER_ROUND
from haze.scheduler.model import Decision, JobRequirement, NodeCandidate

GiB = 1024**3


def _agent(client: TestClient) -> Any:
    return client.app.state.agent  # type: ignore[union-attr]


def _peer(node_id: str = "FASTPEER", **over: Any) -> NodeCandidate:
    """A paired machine that is comfortably faster than this one."""
    base: dict[str, Any] = dict(
        node_id=node_id, name="workstation", cores=32, ram_total=64 * GiB,
        ram_available=48 * GiB, cpu_percent=5.0, speed_factor=8.0,
        runtimes=["hashbench", "ffmpeg"], encoders=[], has_gpu=False,
        latency_ms=2.0, throughput_mbps=940.0, is_self=False, online=True,
    )
    return NodeCandidate(**{**base, **over})


def _this_node(client: TestClient, **over: Any) -> NodeCandidate:
    """The local candidate, shaped as cluster.build shapes it."""
    base: dict[str, Any] = dict(
        node_id=_agent(client).node_id, name="test-node", cores=8,
        ram_total=16 * GiB, ram_available=8 * GiB, cpu_percent=10.0,
        speed_factor=1.0, runtimes=["hashbench"], encoders=[], has_gpu=False,
        is_self=True, online=True,
    )
    return NodeCandidate(**{**base, **over})


@pytest.fixture
def candidates(monkeypatch: pytest.MonkeyPatch):
    """Put a fixed candidate list in front of the scheduler.

    The list is what `cluster.build` would have returned; building it from a
    real peer table would test the database rather than the placement path,
    and none of these tests are about the database.
    """
    def install(nodes: list[NodeCandidate]) -> None:
        async def fake_build(*_a: Any, **_k: Any) -> list[NodeCandidate]:
            return nodes
        monkeypatch.setattr(routes_jobs.cluster, "build", fake_build)

    async def no_probing(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {}
    monkeypatch.setattr(routes_jobs.cluster, "cached_capabilities", no_probing)
    return install


@pytest.fixture
def spy_decide(monkeypatch: pytest.MonkeyPatch) -> list[JobRequirement]:
    """Record what the scheduler was asked, without changing what it answers."""
    seen: list[JobRequirement] = []
    real = routes_jobs.decide

    def recording(nodes: list[NodeCandidate], job: JobRequirement) -> Decision:
        seen.append(job)
        return real(nodes, job)

    monkeypatch.setattr(routes_jobs, "decide", recording)
    return seen


def _submit(client: TestClient, auth: dict[str, str], **body: Any) -> dict[str, Any]:
    response = client.post(
        "/api/v1/jobs",
        headers=auth,
        json={"runtime": "hashbench", "args": {"rounds": 1}, **body},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- choosing ---------------------------------------------------------------

def test_auto_with_only_this_node_runs_here(
    client: TestClient, auth: dict[str, str], candidates: Any
) -> None:
    candidates([_this_node(client)])
    job = _submit(client, auth, placement="auto")

    assert job["placement"]["chosen"] == _agent(client).node_id
    assert job["state"] != "rejected"
    # The local branch stages inputs and runs; the remote branch announces
    # itself in log_tail. This is how we know which one ran.
    assert not any("submitted to" in line for line in job["log_tail"])


def test_auto_sends_a_long_job_to_a_much_faster_peer(
    client: TestClient, auth: dict[str, str], candidates: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates([_this_node(client), _peer()])

    async def never_actually_connects(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"state": "succeeded", "progress": {}, "exit_code": 0}
    monkeypatch.setattr(routes_jobs.node_client, "submit_job_to", never_actually_connects)

    # 8000 rounds is 160 work units against a peer eight times faster, which no
    # amount of transfer cost can overturn -- there is nothing to transfer.
    job = _submit(client, auth, placement="auto", args={"rounds": 8000}, wall_seconds=900)

    assert job["placement"]["chosen"] == "FASTPEER"
    assert job["placement"]["summary"].startswith("workstation")
    assert any("submitted to FASTPEER" in line for line in job["log_tail"])


def test_a_faster_peer_still_loses_when_the_input_must_travel(
    client: TestClient, auth: dict[str, str], candidates: Any, tmp_path: Path
) -> None:
    """The case the whole transfer model exists for.

    A short job with a large input: the peer computes eight times faster and
    still loses, because moving the bytes there and back costs more than it
    saves. If this ever inverts, the scheduler is ranking on speed again.
    """
    payload = tmp_path / "big.bin"
    payload.write_bytes(b"\0" * (24 * 1024 * 1024))
    candidates([_this_node(client), _peer(throughput_mbps=20.0)])

    job = _submit(
        client, auth, placement="auto", args={"rounds": 1}, files=[str(payload)]
    )

    assert job["placement"]["chosen"] == _agent(client).node_id
    assert "computes faster" in job["placement"]["summary"]


# --- what the scheduler is told ---------------------------------------------

def test_input_bytes_are_totalled_from_the_files_being_sent(
    client: TestClient, auth: dict[str, str], candidates: Any,
    spy_decide: list[JobRequirement], tmp_path: Path,
) -> None:
    first, second = tmp_path / "a.bin", tmp_path / "b.bin"
    first.write_bytes(b"x" * 1000)
    second.write_bytes(b"y" * 2345)
    candidates([_this_node(client)])

    _submit(client, auth, placement="auto", files=[str(first), str(second)])

    assert spy_decide[0].input_bytes == 3345


def test_work_units_come_from_the_runtime_when_the_caller_says_nothing(
    client: TestClient, auth: dict[str, str], candidates: Any,
    spy_decide: list[JobRequirement],
) -> None:
    candidates([_this_node(client)])
    _submit(client, auth, placement="auto", args={"rounds": 500})

    assert spy_decide[0].work_units == pytest.approx(500 * SECONDS_PER_ROUND)


def test_an_explicit_work_units_hint_beats_the_runtime_estimate(
    client: TestClient, auth: dict[str, str], candidates: Any,
    spy_decide: list[JobRequirement],
) -> None:
    candidates([_this_node(client)])
    _submit(client, auth, placement="auto", args={"rounds": 500}, work_units=42.0)

    assert spy_decide[0].work_units == 42.0


def test_manual_placement_never_asks_the_scheduler(
    client: TestClient, auth: dict[str, str], spy_decide: list[JobRequirement],
) -> None:
    """The default path must not have grown a probe or a decision."""
    _submit(client, auth)
    assert spy_decide == []


# --- when nothing can run it ------------------------------------------------

def test_no_eligible_node_is_a_rejection_carrying_the_summary_verbatim(
    client: TestClient, auth: dict[str, str], candidates: Any,
) -> None:
    """Delivered as a rejected job, not an HTTP error.

    That is this codebase's existing answer to a request it will not run -- so
    the job appears in the list next to the others with its reason on it,
    rather than vanishing into a status code.
    """
    candidates([
        _this_node(client, runtimes=["blender"]),
        _peer(runtimes=["blender"]),
    ])
    job = _submit(client, auth, placement="auto")

    assert job["state"] == "rejected"
    assert job["error"] == job["placement"]["summary"]
    assert job["error"].startswith("no node can run hashbench")
    # Every candidate says why, not just the first.
    assert "test-node" in job["error"] and "workstation" in job["error"]


def test_an_empty_cluster_is_not_a_crash(
    client: TestClient, auth: dict[str, str], candidates: Any,
) -> None:
    candidates([])
    job = _submit(client, auth, placement="auto")

    assert job["state"] == "rejected"
    assert job["error"] == "no nodes available"


# --- the request shape ------------------------------------------------------

def test_auto_together_with_a_node_id_is_refused(
    client: TestClient, auth: dict[str, str],
) -> None:
    """Self-contradictory: guessing which half was meant is how a scheduler
    earns distrust."""
    response = client.post(
        "/api/v1/jobs",
        headers=auth,
        json={"runtime": "hashbench", "placement": "auto", "node_id": "SOMEPEER"},
    )
    assert response.status_code == 400
    assert "node_id" in response.json()["detail"]


def test_an_unknown_placement_mode_is_rejected_at_the_edge(
    client: TestClient, auth: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/jobs",
        headers=auth,
        json={"runtime": "hashbench", "placement": "atuo"},
    )
    assert response.status_code == 422
