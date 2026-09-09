"""The runtime allowlist.

A runtime turns validated, typed arguments into an argv. Nothing a peer sends
ever becomes a command name, a shell fragment, or a path outside the job's own
directory. Adding a capability to Haze means adding a runtime here on purpose,
not widening a string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from haze.jobs.progress import ProgressParser


class JobArgumentError(Exception):
    """Arguments a runtime will not accept.

    The message reaches the submitting peer verbatim, so it is written for a
    human on another machine: say what was wrong and what would be accepted.
    """


@dataclass
class Prepared:
    """Everything the executor needs to run one job."""

    argv: list[str]
    parser: ProgressParser
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    outputs_from: str = "explicit"
    """How completed outputs are discovered: "explicit" (the runtime lists
    them) or "parser" (the parser collects them, as Blender's Saved: lines do)."""
    explicit_outputs: list[Path] = field(default_factory=list)


DEFAULT_WORK_UNITS = 10.0
"""What a job is worth to the scheduler when nothing better can be said.

Ten seconds on a baseline node -- long enough that transfer cost still matters
on a large input, short enough not to pretend every unknown job is a render
farm's worth of work.
"""


class Runtime(Protocol):
    """One kind of work Haze knows how to do."""

    name: str
    description: str

    def available(self) -> bool:
        """Whether this node can run it at all (is the tool installed?)."""
        ...

    def prepare(self, args: dict[str, Any], workdir: Path) -> Prepared:
        """Validate arguments and build the command. Raises JobArgumentError."""
        ...

    def estimate_work_units(self, args: dict[str, Any], inputs: list[Path]) -> float:
        """Roughly how much compute this job is, in scheduler work units.

        One unit is one second on a node with ``speed_factor`` 1.0. Only ratios
        matter -- and really only the ratio against *transfer* time, because
        work_units scales every candidate's compute term identically. An
        estimate that is 2x out moves where the compute-versus-transfer
        crossover falls; it cannot reorder two nodes on compute alone. That is
        why a documented constant is defensible here and a fabricated
        measurement would not be.

        ``inputs`` are resolved paths on *this* machine, not the job directory:
        placement happens before anything is staged. Return
        ``DEFAULT_WORK_UNITS`` when there is no honest basis for a number.

        Called off the event loop -- it may stat files or shell out to ffprobe.
        """
        ...


REGISTRY: dict[str, Runtime] = {}


def register(runtime: Runtime) -> Runtime:
    REGISTRY[runtime.name] = runtime
    return runtime


def get(name: str) -> Runtime:
    runtime = REGISTRY.get(name)
    if runtime is None:
        raise JobArgumentError(
            f"unknown runtime {name!r}. This node runs: {', '.join(sorted(REGISTRY)) or 'nothing'}"
        )
    return runtime


def available_names() -> list[str]:
    return sorted(name for name, rt in REGISTRY.items() if rt.available())


def estimate_work_units(name: str, args: dict[str, Any], inputs: list[Path]) -> float:
    """Ask a runtime what a job costs, tolerating a name it does not know.

    An unknown runtime is not this function's error to raise: the executor
    rejects it a moment later with a message written for the submitter. Here it
    is simply a job we cannot size, which is what the default is for.
    """
    runtime = REGISTRY.get(name)
    if runtime is None:
        return DEFAULT_WORK_UNITS
    return runtime.estimate_work_units(args, inputs)


def safe_join(root: Path, candidate: str) -> Path:
    """Resolve ``candidate`` strictly inside ``root``.

    Guards the whole class of path-traversal tricks -- ``..``, absolute paths,
    symlinks pointing outward -- by resolving fully and then checking
    containment, rather than by pattern-matching the input string.
    """
    if not candidate or candidate.strip() != candidate:
        raise JobArgumentError("empty or padded path")
    resolved = (root / candidate).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise JobArgumentError(f"path {candidate!r} escapes the job directory")
    return resolved
