"""Recoverable on-disk conditions, and bounded growth.

Both classes of bug here were found by poking at a running agent rather than by
reading the code, and both are the kind that only bite after the project looks
finished: an agent left running for a week, or a config file that got truncated
by a full disk.
"""

from __future__ import annotations

import asyncio
import os
import socket
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from haze.identity import keys
from haze.jobs.executor import JobExecutor, new_job_id
from haze.jobs.spec import JobSpec, ResourceRequest

# --- on-disk state a human has to fix ---------------------------------------

def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "haze", *args],
        env={**os.environ, "HAZE_HOME": str(home)},
        capture_output=True, text=True, timeout=60, check=False,
    )


def test_a_corrupt_config_names_the_file_and_the_remedy(tmp_path: Path) -> None:
    """`JSONDecodeError: Expecting value: line 1 column 1` tells a user nothing
    about which file broke or what to do."""
    home = tmp_path / "haze"
    home.mkdir(mode=0o700)
    (home / "config.json").write_text("this is not json")
    (home / "config.json").chmod(0o600)

    result = _run_cli(home, "id")
    assert result.returncode == 1
    assert "config.json" in result.stderr
    assert "not valid JSON" in result.stderr
    assert "rm " in result.stderr, "the message should include the fix"
    assert "Traceback" not in result.stderr, "a fixable condition must not look like a crash"


def test_a_truncated_identity_key_is_explained(tmp_path: Path) -> None:
    home = tmp_path / "haze"
    home.mkdir(mode=0o700)
    (home / "identity.key").write_bytes(b"too short")
    (home / "identity.key").chmod(0o600)

    result = _run_cli(home, "id")
    assert result.returncode == 1
    assert "32" in result.stderr and "corrupt" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(
    os.name != "posix",
    reason="there are no POSIX mode bits to be wrong about on Windows",
)
def test_a_readable_private_key_is_refused_not_repaired(tmp_path: Path) -> None:
    """Silently chmod-ing it would hide a possible key exposure from the only
    person who can act on it.

    POSIX-only, and not merely because ``chmod(0o644)`` cannot express "group
    and world readable" on Windows: the agent deliberately does not read mode
    bits there at all, because NTFS ACLs are what actually govern the file and
    the mode bits Python synthesises say nothing true about them. There is no
    behaviour to assert here on Windows -- refusing to start over a fabricated
    0644 would be the bug.
    """
    home = tmp_path / "haze"
    home.mkdir(mode=0o700)
    monkeypatched = os.environ.get("HAZE_HOME")
    os.environ["HAZE_HOME"] = str(home)
    try:
        keys.load_or_create()
    finally:
        if monkeypatched is None:
            del os.environ["HAZE_HOME"]
        else:
            os.environ["HAZE_HOME"] = monkeypatched

    (home / "identity.key").chmod(0o644)
    result = _run_cli(home, "id")
    assert result.returncode == 1
    assert "0644" in result.stderr
    assert "Traceback" not in result.stderr
    # And it really did refuse rather than fixing it up.
    assert stat.S_IMODE((home / "identity.key").stat().st_mode) == 0o644


def test_a_healthy_agent_is_unaffected(tmp_path: Path) -> None:
    result = _run_cli(tmp_path / "haze", "id")
    assert result.returncode == 0
    assert "short" in result.stdout


def test_debug_still_gives_a_traceback(tmp_path: Path) -> None:
    """The clean message must not cost the ability to debug."""
    home = tmp_path / "haze"
    home.mkdir(mode=0o700)
    (home / "identity.key").write_bytes(b"short")
    (home / "identity.key").chmod(0o600)

    result = subprocess.run(
        [sys.executable, "-m", "haze", "id"],
        env={**os.environ, "HAZE_HOME": str(home), "HAZE_DEBUG": "1"},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert "Traceback" in result.stderr


# --- a port someone else already has ----------------------------------------

def test_a_busy_node_port_names_the_flag_that_fixes_it(tmp_path: Path) -> None:
    """`haze up` used to print a full success banner -- Console URL included --
    and then die in uvicorn's lifespan with `OSError: [Errno 48]`.

    The dashboard port is scanned when it is busy, but the node port cannot be:
    peers are told it during the handshake and call back on it. So the only
    honest outcome is a refusal that names the remedy.
    """
    home = tmp_path / "haze"
    home.mkdir(mode=0o700)

    # An ephemeral port, not a fixed one: conftest notes that binding a known
    # port makes the suite fail whenever a real agent is running here.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as squatter:
        squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        squatter.bind(("0.0.0.0", 0))  # noqa: S104
        squatter.listen(1)
        taken = squatter.getsockname()[1]

        result = _run_cli(home, "up", "--no-open", "--node-port", str(taken))

    assert result.returncode == 1
    assert str(taken) in result.stderr
    assert "--node-port" in result.stderr, "the message should include the fix"
    assert "haze status" in result.stderr, "it should say how to find the other agent"
    assert "Traceback" not in result.stderr, "a fixable condition must not look like a crash"
    # The banner and the browser tab are the actual damage: an agent that is
    # about to exit must not first tell the user where its console is.
    assert "Console:" not in result.stdout


def test_a_free_node_port_is_not_disturbed(tmp_path: Path) -> None:
    """The pre-flight must not reject a port that is genuinely available."""
    from haze import config

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))  # noqa: S104
        taken = s.getsockname()[1]
        assert config.port_is_free(taken, host="0.0.0.0") is False  # noqa: S104

    # Same port, now that the socket is closed.
    assert config.port_is_free(taken, host="0.0.0.0") is True  # noqa: S104


# --- bounded growth ---------------------------------------------------------

async def _drain(executor: JobExecutor, rounds: int = 1) -> None:
    spec = JobSpec(
        job_id=new_job_id(), runtime="hashbench", args={"rounds": rounds},
        resources=ResourceRequest(cpu_cores=1, ram_bytes=1 << 30, wall_seconds=60),
    )
    record = executor.submit(spec)
    await _wait(lambda: record.state.terminal, "job did not finish")


async def _wait(predicate: Callable[[], bool], message: str, timeout_s: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.05)


async def test_finished_jobs_do_not_accumulate_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent left running must not grow without bound.

    The worst part was on disk: every job keeps a working directory, and for a
    render job that is all its output frames.
    """
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    executor.retain_finished = 5

    for _ in range(20):
        await _drain(executor)

    assert len(executor.all_jobs()) <= 6
    job_dirs = list((tmp_path / "jobs").glob("*"))
    assert len(job_dirs) <= 6, f"{len(job_dirs)} job directories left on disk"
    # Pruning runs from inside the finishing job's own task, so that one is
    # not yet done() and survives until the next prune. Bounded, which is
    # the property that matters -- it was previously unbounded.
    assert len(executor._tasks) <= 2, executor._tasks
    await executor.shutdown()


async def test_a_running_job_is_never_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retention counts finished jobs only. Evicting a running one would lose
    work and orphan its subprocess."""
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    executor.retain_finished = 2

    long_spec = JobSpec(
        job_id=new_job_id(), runtime="hashbench", args={"rounds": 100_000},
        resources=ResourceRequest(cpu_cores=1, ram_bytes=1 << 30, wall_seconds=120),
    )
    running = executor.submit(long_spec)
    await _wait(lambda: running.state.value == "running", "long job never started")

    for _ in range(10):
        await _drain(executor)

    assert executor.get(long_spec.job_id) is not None, "the running job was pruned"
    assert running.state.value == "running"
    await executor.cancel(long_spec.job_id)
    await executor.shutdown()


def test_orphaned_job_directories_are_swept_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent killed mid-job leaves a directory nothing else would remove."""
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    orphan = tmp_path / "jobs" / "deadbeef"
    orphan.mkdir(parents=True)
    (orphan / "big-render-output.png").write_bytes(b"x" * 1024)

    removed = JobExecutor().sweep_orphaned_dirs()
    assert removed == 1
    assert not orphan.exists()
