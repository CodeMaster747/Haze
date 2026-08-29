"""Resource probes: the real machine, and the fabricated ones."""

from __future__ import annotations

import pytest

from haze.probe import encoders, synthetic
from haze.probe.host import HostProbe

# --- host -------------------------------------------------------------------

def test_host_probe_reports_this_machine() -> None:
    probe = HostProbe("test")
    snapshot = probe.sample()

    assert probe.simulated is False
    assert snapshot.cpu.cores >= 1
    assert len(snapshot.cpu.per_core) == snapshot.cpu.cores
    assert 0 <= snapshot.cpu.percent <= 100
    assert snapshot.ram.total > 0
    assert snapshot.ram.used + snapshot.ram.available == snapshot.ram.total
    assert snapshot.disk.total > 0


def test_host_probe_serialises_to_the_wire_shape() -> None:
    data = HostProbe("test").sample().to_dict()
    assert set(data) >= {"node_name", "ts", "uptime_s", "cpu", "ram", "disk", "gpu"}
    assert set(data["cpu"]) == {"percent", "per_core", "cores", "physical_cores"}


def test_gpu_is_either_absent_or_complete() -> None:
    """A partially-filled GPU record would render as a meaningless meter."""
    gpu = HostProbe("test").sample().gpu
    if gpu is None:
        pytest.skip("no GPU readable on this machine")
    assert gpu.vendor in {"nvidia", "apple", "amd", "intel"}
    assert gpu.name
    # vram_total is legitimately None on unified-memory hardware; utilisation
    # may be None if the platform will not report it without elevation. Both
    # are honest states the UI renders as a dash.
    if gpu.vram_total is not None:
        assert gpu.vram_total > 0


def test_encoder_detection_degrades_without_ffmpeg() -> None:
    """A machine with no ffmpeg simply never wins an encode placement."""
    result = encoders.detect()
    assert isinstance(result, list)
    assert all(isinstance(name, str) for name in result)


# --- synthetic --------------------------------------------------------------

def test_every_shipped_profile_loads() -> None:
    names = synthetic.available()
    assert {"workstation", "laptop", "nas", "builder"} <= set(names)
    for name in names:
        profile = synthetic.load(name)
        assert profile.cores > 0
        assert profile.ram_bytes > 0
        assert profile.speed_factor > 0


def test_unknown_profile_names_the_alternatives() -> None:
    with pytest.raises(FileNotFoundError, match="Available:"):
        synthetic.load("no-such-profile")


def test_synthetic_probe_is_deterministic() -> None:
    """Same seed, same trace -- in development and in CI.

    This is what will let the browser simulation be checked against the Python
    scheduler later; an unseeded probe would make that impossible.
    """
    profile = synthetic.load("workstation")
    first = [synthetic.SyntheticProbe(profile, seed=7).sample().cpu.percent for _ in range(20)]
    second = [synthetic.SyntheticProbe(profile, seed=7).sample().cpu.percent for _ in range(20)]
    assert first == second


def test_different_seeds_diverge() -> None:
    profile = synthetic.load("workstation")
    a = [synthetic.SyntheticProbe(profile, seed=1).sample().cpu.percent for _ in range(20)]
    b = [synthetic.SyntheticProbe(profile, seed=2).sample().cpu.percent for _ in range(20)]
    assert a != b


def test_synthetic_load_stays_in_range_and_actually_moves() -> None:
    """Mean-reverting, not a random walk: a walk drifts to a rail and sticks."""
    probe = synthetic.SyntheticProbe(synthetic.load("builder"), seed=3)
    samples = [probe.sample().cpu.percent for _ in range(500)]

    assert all(0 <= s <= 100 for s in samples)
    assert len(set(samples)) > 50, "load should vary, not sit still"
    mean = sum(samples) / len(samples)
    assert abs(mean - 31.0) < 12, f"should revert toward the profile's mean, got {mean:.1f}"


def test_synthetic_nodes_are_always_flagged_simulated() -> None:
    """The badge is a correctness requirement, not decoration: an unbadged fake
    RTX 4090 on a machine with no NVIDIA GPU is indistinguishable from a lie."""
    for name in synthetic.available():
        assert synthetic.SyntheticProbe(synthetic.load(name)).simulated is True


def test_unified_memory_reports_no_vram_total() -> None:
    """The laptop profile mirrors the real Apple probe, which cannot report a
    device VRAM total -- there is no separate pool, and ioreg exposes none."""
    snapshot = synthetic.SyntheticProbe(synthetic.load("laptop")).sample()
    assert snapshot.gpu is not None
    assert snapshot.gpu.vram_total is None


def test_per_core_matches_the_profile() -> None:
    snapshot = synthetic.SyntheticProbe(synthetic.load("workstation")).sample()
    assert len(snapshot.cpu.per_core) == 16
    assert len(set(snapshot.cpu.per_core)) > 1, "cores should not all read identically"
