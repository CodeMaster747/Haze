"""The scheduler, and the golden corpus that keeps its TypeScript twin honest.

`decide` is a pure function, so this file both tests it and *writes*
`tests/conformance/scheduler_cases.json`: a set of (nodes, job) -> decision
records. `web/tests/conformance.test.ts` replays the same corpus against the
TypeScript implementation the browser demo runs, and fails if any decision
differs.

That is what makes the deployed demo provably the same algorithm rather than a
plausible-looking imitation of it. Regenerate with:

    pytest agent/tests/test_scheduler.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from haze.scheduler.decide import decide
from haze.scheduler.model import JobRequirement, NodeCandidate

CORPUS_PATH = Path(__file__).parent / "conformance" / "scheduler_cases.json"
GiB = 1024**3
MiB = 1024**2


def _laptop(**over: Any) -> NodeCandidate:
    base: dict[str, Any] = dict(
        node_id="LAPTOP1", name="laptop", cores=10, ram_total=24 * GiB,
        ram_available=12 * GiB, cpu_percent=25.0, speed_factor=1.0,
        runtimes=["hashbench", "blender"], encoders=["h264_videotoolbox"],
        has_gpu=True, gpu_name="Apple M4", latency_ms=0.0, throughput_mbps=1000.0,
        is_self=True,
    )
    return NodeCandidate(**{**base, **over})


def _workstation(**over: Any) -> NodeCandidate:
    base: dict[str, Any] = dict(
        node_id="DESKTOP", name="workstation", cores=16, ram_total=64 * GiB,
        ram_available=48 * GiB, cpu_percent=15.0, speed_factor=4.2,
        runtimes=["hashbench", "blender", "ffmpeg"],
        encoders=["h264_nvenc", "hevc_nvenc", "av1_nvenc"],
        has_gpu=True, gpu_name="RTX 4090", latency_ms=2.0, throughput_mbps=940.0,
    )
    return NodeCandidate(**{**base, **over})


def _nas(**over: Any) -> NodeCandidate:
    base: dict[str, Any] = dict(
        node_id="NASBOX1", name="nas", cores=4, ram_total=8 * GiB,
        ram_available=6 * GiB, cpu_percent=5.0, speed_factor=0.4,
        runtimes=["hashbench"], encoders=[], has_gpu=False,
        latency_ms=8.0, throughput_mbps=90.0,
    )
    return NodeCandidate(**{**base, **over})


CASES: list[tuple[str, list[NodeCandidate], JobRequirement]] = [
    (
        "gpu render goes to the fast machine",
        [_laptop(), _workstation(), _nas()],
        JobRequirement("blender", 4, 2 * GiB, True, [], 50 * MiB, 600.0),
    ),
    (
        "tiny job with no inputs still goes to the fast machine",
        [_laptop(), _workstation(), _nas()],
        JobRequirement("hashbench", 1, 256 * MiB, False, [], 0, 2.0),
    ),
    (
        "a big upload beats a fast CPU",
        [_laptop(), _workstation(), _nas()],
        JobRequirement("blender", 2, GiB, False, [], 900 * MiB, 8.0),
    ),
    (
        "only one node has the runtime",
        [_laptop(), _workstation(), _nas()],
        JobRequirement("ffmpeg", 2, GiB, False, ["h264_nvenc"], 20 * MiB, 60.0),
    ),
    (
        "nobody has the runtime",
        [_laptop(), _nas()],
        JobRequirement("ffmpeg", 1, GiB, False, [], 0, 10.0),
    ),
    (
        "the fast machine is busy",
        [_laptop(cpu_percent=5.0), _workstation(cpu_percent=95.0), _nas()],
        JobRequirement("hashbench", 1, GiB, False, [], 0, 100.0),
    ),
    (
        "the fast machine is offline",
        [_laptop(), _workstation(online=False), _nas()],
        JobRequirement("hashbench", 1, GiB, False, [], 0, 50.0),
    ),
    (
        "memory rules a node out",
        [_laptop(ram_available=1 * GiB), _workstation(), _nas()],
        JobRequirement("blender", 2, 8 * GiB, False, [], 10 * MiB, 100.0),
    ),
    (
        "core count rules a node out",
        [_laptop(), _workstation(), _nas()],
        JobRequirement("hashbench", 8, GiB, False, [], 0, 20.0),
    ),
    (
        "a slow link makes a fast node lose",
        [_laptop(), _workstation(throughput_mbps=5.0, latency_ms=90.0)],
        JobRequirement("blender", 2, GiB, False, [], 200 * MiB, 30.0),
    ),
    (
        "no nodes at all",
        [],
        JobRequirement("hashbench", 1, GiB, False, [], 0, 1.0),
    ),
    (
        "encoder preference is explained even when it changes nothing",
        [_workstation(), _laptop()],
        JobRequirement("blender", 1, GiB, False, ["hevc_nvenc"], 1 * MiB, 5.0),
    ),
]


def test_the_scheduler_is_pure() -> None:
    """Same inputs, same decision -- every time, in any process."""
    nodes = [_laptop(), _workstation(), _nas()]
    job = JobRequirement("blender", 2, GiB, True, ["hevc_nvenc"], 30 * MiB, 120.0)
    first = decide(nodes, job).to_dict()
    for _ in range(20):
        assert decide(nodes, job).to_dict() == first


def test_ordering_is_total_so_the_corpus_cannot_be_flaky() -> None:
    """Two identically-scored nodes must always order the same way, or the
    conformance corpus would be flaky rather than wrong."""
    twin_a = _nas(node_id="AAA")
    twin_b = _nas(node_id="BBB")
    job = JobRequirement("hashbench", 1, GiB, False, [], 0, 5.0)

    forward = [a.node_id for a in decide([twin_a, twin_b], job).assessments]
    backward = [a.node_id for a in decide([twin_b, twin_a], job).assessments]
    assert forward == backward == ["AAA", "BBB"]


def test_a_big_upload_beats_a_fast_cpu() -> None:
    """The behaviour that justifies having a scheduler at all.

    An earlier scoring model normalised transfer cost against the other
    candidates, so the only remote node always scored 1.0 on it and this case
    chose an 18s round trip over a 10s local run.
    """
    decision = decide(
        [_laptop(), _workstation()],
        JobRequirement("blender", 2, GiB, False, [], 900 * MiB, 8.0),
    )
    assert decision.chosen == "LAPTOP1"
    assert "computes faster" in decision.summary
    assert "transfer" in decision.summary


def test_ineligibility_is_elimination_not_a_low_score() -> None:
    """"You do not have Blender" must not be something a fast enough node can
    outweigh."""
    decision = decide(
        [_workstation(runtimes=["hashbench"]), _nas(runtimes=["blender"], speed_factor=0.1)],
        JobRequirement("blender", 1, GiB, False, [], 0, 10.0),
    )
    assert decision.chosen == "NASBOX1"
    workstation = next(a for a in decision.assessments if a.node_id == "DESKTOP")
    assert workstation.eligible is False
    assert "does not have blender" in workstation.reasons[0]


def test_every_candidate_is_reported_including_losers() -> None:
    """`haze explain` shows why each candidate lost, so nothing is dropped."""
    decision = decide([_laptop(), _workstation(), _nas()],
                      JobRequirement("hashbench", 1, GiB, False, [], 0, 10.0))
    assert len(decision.assessments) == 3
    assert all(a.reasons for a in decision.assessments)


def test_no_eligible_node_says_why_for_each() -> None:
    decision = decide([_laptop(), _nas()],
                      JobRequirement("ffmpeg", 1, GiB, False, [], 0, 1.0))
    assert decision.chosen is None
    assert "laptop" in decision.summary and "nas" in decision.summary


def test_empty_cluster_is_not_a_crash() -> None:
    decision = decide([], JobRequirement("hashbench", 1, GiB, False, [], 0, 1.0))
    assert decision.chosen is None
    assert decision.assessments == []


@pytest.mark.parametrize("name,nodes,job", CASES, ids=[c[0] for c in CASES])
def test_each_corpus_case_produces_a_decision(
    name: str, nodes: list[NodeCandidate], job: JobRequirement
) -> None:
    decision = decide(nodes, job)
    assert len(decision.assessments) == len(nodes)
    if decision.chosen is not None:
        assert any(a.node_id == decision.chosen and a.eligible for a in decision.assessments)


def test_write_the_conformance_corpus() -> None:
    """Not really a test -- this generates the goldens the TypeScript suite
    replays. Kept in pytest so it cannot drift out of date: change the
    scheduler without regenerating and `git diff` shows it immediately.
    """
    corpus = [
        {
            "name": name,
            "nodes": [n.to_dict() for n in nodes],
            "job": job.to_dict(),
            "expected": decide(nodes, job).to_dict(),
        }
        for name, nodes, job in CASES
    ]
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n")

    reloaded = json.loads(CORPUS_PATH.read_text())
    assert len(reloaded) == len(CASES)
    # Round-trips through the dict form without changing the decision, which is
    # what the TypeScript side will consume.
    for entry in reloaded:
        nodes = [NodeCandidate.from_dict(n) for n in entry["nodes"]]
        job = JobRequirement.from_dict(entry["job"])
        assert decide(nodes, job).to_dict() == entry["expected"]
