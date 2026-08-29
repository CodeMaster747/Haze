"""Where should this job run?

A pure function. No clock, no randomness, no I/O, no ambient state -- the same
inputs always produce the same decision, in this process, in CI, and in the
TypeScript mirror the browser demo runs. `tests/test_scheduler.py` writes a
golden corpus of (state, job) -> decision pairs, and a vitest suite replays it
against the TypeScript implementation. That is what makes the deployed demo
provably the same algorithm rather than a plausible-looking imitation.

The model
---------
Two stages. First a hard gate: a node either *can* run the job or it cannot,
and "cannot" is never a low score -- it is elimination with a stated reason.

Then the ranking, which **minimises predicted end-to-end time**:

    total = compute_seconds + transfer_seconds

That is the thing a user actually cares about, and ranking on it directly means
a node that computes twice as fast genuinely loses when the link costs more
than it saves -- which is the behaviour `haze bench --compare` measures.

An earlier version scored a weighted average of normalised dimensions instead,
and it was wrong in an instructive way: `transfer` was normalised against the
other candidates, so the cheapest remote node always scored 1.0 on it. With one
remote node the dimension could never penalise anything, and the scheduler
happily chose an 18-second round trip over a 10-second local run.

The four dimensions survive as **explanation**, not as the ranking. They are
what `haze explain` prints, and each is scaled so 1.0 is the best any candidate
achieved on that axis in this decision.

Floating point
--------------
Both Python and JavaScript use IEEE 754 doubles, so the arithmetic agrees --
but their rounding functions do not (Python's `round` is banker's rounding,
JavaScript's `toFixed` rounds half away from zero). `_round` below is defined
identically in both, and is the only rounding either implementation uses.
"""

from __future__ import annotations

import math

from haze.scheduler.model import Assessment, Decision, JobRequirement, NodeCandidate

# Weights sum to 1.0. Tuned so that transfer cost can genuinely overturn a raw
# speed advantage on small jobs, which is the behaviour the benchmark shows.
WEIGHTS = {
    "speed": 0.40,
    "headroom": 0.20,
    "transfer": 0.30,
    "affinity": 0.10,
}

# Bytes/second assumed when a node has never been measured. Deliberately
# pessimistic: over-estimating a link makes the scheduler ship work somewhere
# it should not have.
DEFAULT_THROUGHPUT_MBPS = 100.0

# A job smaller than this is treated as having no transfer cost at all --
# below it, latency dominates and the arithmetic is noise.
NEGLIGIBLE_INPUT_BYTES = 64 * 1024


def _round(value: float) -> float:
    """Round to 4 decimals, identically in Python and JavaScript.

    Python's built-in `round` uses banker's rounding and JavaScript's `toFixed`
    rounds half away from zero, so neither is safe for a value the two
    implementations must agree on exactly. `floor(x * 10^4 + 0.5) / 10^4` is
    unambiguous in both.
    """
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return math.floor(value * 10000 + 0.5) / 10000


def _fmt(value: float) -> str:
    """Format a number for a human-readable reason string.

    Neither language's native decimal formatting can be used here. Python's
    ``f"{v:.2f}"`` rounds half to even and JavaScript's ``toFixed`` rounds half
    away from zero, so 0.125 becomes "0.12" in one and "0.13" in the other --
    a divergence the conformance corpus caught immediately.

    So the value is rounded with the same floor-based expression both languages
    agree on, and the string is then assembled from integers, which are exact
    in both. Its twin lives in web/src/sim/scheduler.ts and must stay identical.

    10.0 -> "10", 6.25 -> "6.25", 0.5 -> "0.5", 0.125 -> "0.13".
    """
    negative = value < 0
    hundredths = math.floor(abs(value) * 100 + 0.5)
    whole, frac = hundredths // 100, hundredths % 100

    if frac == 0:
        text = str(whole)
    elif frac % 10 == 0:
        text = f"{whole}.{frac // 10}"
    else:
        text = f"{whole}.{frac:02d}"
    return f"-{text}" if negative and hundredths else text


def _transfer_seconds(node: NodeCandidate, job: JobRequirement) -> float:
    """Time to move the inputs there and the outputs back.

    Outputs are assumed to be roughly the size of the inputs. Crude, but the
    alternative is pretending transfer is free, and being roughly right about a
    real cost beats being exactly right about an imaginary one.
    """
    if node.is_self or job.input_bytes <= NEGLIGIBLE_INPUT_BYTES:
        return 0.0
    mbps = node.throughput_mbps if node.throughput_mbps > 0 else DEFAULT_THROUGHPUT_MBPS
    bytes_each_way = job.input_bytes * 2
    seconds = (bytes_each_way * 8) / (mbps * 1_000_000)
    # One round trip of protocol overhead, doubled for request and response.
    return seconds + (node.latency_ms * 2) / 1000.0


def _compute_seconds(node: NodeCandidate, job: JobRequirement) -> float:
    """How long the work itself would take here."""
    speed = node.speed_factor if node.speed_factor > 0 else 0.01
    # Current load slows things down, but never to a standstill: a busy machine
    # is slower, not unusable.
    contention = 1.0 + (min(100.0, max(0.0, node.cpu_percent)) / 100.0)
    return (job.work_units / speed) * contention


def _ineligibility(node: NodeCandidate, job: JobRequirement) -> str | None:
    """Why this node cannot run the job at all, or None if it can.

    These are hard gates rather than low scores. "You do not have Blender
    installed" is not a node being unattractive, and blending it into a
    weighted average would let a fast enough machine win a job it cannot run.
    """
    if not node.online:
        return "offline"
    if job.runtime not in node.runtimes:
        return f"does not have {job.runtime}"
    if node.cores < job.cpu_cores:
        return f"has {node.cores} cores, job needs {job.cpu_cores}"
    if node.ram_available < job.ram_bytes:
        need = job.ram_bytes // (1 << 20)
        have = node.ram_available // (1 << 20)
        return f"has {have} MiB free, job needs {need} MiB"
    if job.needs_gpu and not node.has_gpu:
        return "has no GPU"
    return None


def _assess(
    node: NodeCandidate,
    job: JobRequirement,
    fastest_compute: float,
    fastest_total: float,
) -> Assessment:
    compute = _compute_seconds(node, job)
    transfer = _transfer_seconds(node, job)
    total = compute + transfer

    # THE ranking number. Everything below is explanation.
    score = _round(fastest_total / total) if total > 0 else 1.0

    dimensions = {
        # How fast this node computes, best-in-decision = 1.0.
        "speed": _round(fastest_compute / compute) if compute > 0 else 1.0,
        # How much of it is currently free.
        "headroom": _round(1.0 - (min(100.0, max(0.0, node.cpu_percent)) / 100.0)),
        # What fraction of the total goes on real work rather than moving bytes.
        # Absolute, not relative to peers -- that was the bug.
        "transfer": _round(compute / total) if total > 0 else 1.0,
        # Does it have hardware this job asked for.
        "affinity": _affinity(node, job),
    }

    reasons: list[str] = []
    if node.is_self:
        reasons.append("runs here — nothing to transfer")
    elif transfer > 0.05:
        share = int(_round(transfer / total * 100)) if total > 0 else 0
        reasons.append(
            f"{_fmt(transfer)}s moving {job.input_bytes // 1024} KiB each way "
            f"({share}% of the total)"
        )
    reasons.append(f"~{_fmt(compute)}s of compute at {_fmt(node.speed_factor)}×")
    if node.cpu_percent >= 70:
        reasons.append(f"busy — {_fmt(node.cpu_percent)}% CPU already")
    wanted = set(job.preferred_encoders)
    if wanted:
        matched_names = sorted(wanted & set(node.encoders))
        reasons.append(
            f"has {', '.join(matched_names)}" if matched_names else "no preferred encoder"
        )
    if job.needs_gpu and node.has_gpu and node.gpu_name:
        reasons.append(f"GPU: {node.gpu_name}")

    return Assessment(
        node_id=node.node_id,
        name=node.name,
        eligible=True,
        score=score,
        dimensions=dimensions,
        reasons=reasons,
        estimated_seconds=_round(total),
    )


def _affinity(node: NodeCandidate, job: JobRequirement) -> float:
    wanted = set(job.preferred_encoders)
    if not wanted:
        return 1.0 if (not job.needs_gpu or node.has_gpu) else 0.0
    return _round(len(wanted & set(node.encoders)) / len(wanted))


def decide(nodes: list[NodeCandidate], job: JobRequirement) -> Decision:
    """Choose a node. Pure: same inputs, same decision, always."""
    if not nodes:
        return Decision(chosen=None, assessments=[], summary="no nodes available")

    eligible: list[NodeCandidate] = []
    assessments: list[Assessment] = []

    for node in nodes:
        reason = _ineligibility(node, job)
        if reason is None:
            eligible.append(node)
        else:
            assessments.append(
                Assessment(
                    node_id=node.node_id, name=node.name, eligible=False, score=0.0,
                    dimensions={}, reasons=[reason], estimated_seconds=0.0,
                )
            )

    if not eligible:
        return Decision(
            chosen=None,
            assessments=_ordered(assessments),
            summary=f"no node can run {job.runtime}: " +
                    "; ".join(f"{a.name} {a.reasons[0]}" for a in assessments),
        )

    fastest_compute = min(_compute_seconds(n, job) for n in eligible)
    fastest_total = min(_compute_seconds(n, job) + _transfer_seconds(n, job) for n in eligible)

    assessments += [_assess(n, job, fastest_compute, fastest_total) for n in eligible]
    ordered = _ordered(assessments)
    winner = ordered[0]

    runner_up = next((a for a in ordered[1:] if a.eligible), None)
    if runner_up is None:
        summary = f"{winner.name} was the only node that could run it"
    else:
        margin = _fmt(runner_up.estimated_seconds - winner.estimated_seconds)
        winner_computes_slower = (
            winner.dimensions.get("speed", 1.0) < runner_up.dimensions.get("speed", 1.0)
        )
        if winner_computes_slower:
            # The interesting case, and the reason transfer is modelled at all:
            # the faster machine lost because getting the work there cost more
            # than it saved.
            summary = (
                f"{winner.name} — {runner_up.name} computes faster but is "
                f"{margin}s slower end to end once transfer is counted"
            )
        else:
            summary = f"{winner.name} — {margin}s faster than {runner_up.name} end to end"

    return Decision(chosen=winner.node_id, assessments=ordered, summary=summary)


def _ordered(assessments: list[Assessment]) -> list[Assessment]:
    """Best first, ineligible last.

    Ties break on node_id so the ordering is total and reproducible -- without
    it, two equally-scored nodes could order differently between runs and the
    conformance corpus would be flaky rather than wrong.
    """
    return sorted(assessments, key=lambda a: (not a.eligible, -a.score, a.node_id))
