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
