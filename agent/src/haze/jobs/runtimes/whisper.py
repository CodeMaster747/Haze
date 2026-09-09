"""Speech transcription, with faster-whisper.

The best-economics job Haze runs. A few megabytes of audio go out, a few
kilobytes of text come back, and minutes of GPU decode happen in between --
which is the case where the transfer cost the scheduler models is negligible
against the compute, so a remote node wins even on a short job.

faster-whisper is a *library*, not a binary, so this follows hashbench's shape
rather than ffmpeg's: the runtime builds an argv that runs this same module as
``python -m``. Going through the normal subprocess path is the point -- rlimits,
the process group, niceness and the kill timer all apply exactly as they do to
ffmpeg, which they would not if we imported a 3 GB model into the agent.

It is an optional extra (``pip install 'haze-agent[whisper]'``). A node without
it reports ``available() == False``, which flows to peers through
``available_names()`` and makes the scheduler rule that node ineligible with a
reason. That path needs no scheduler change.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from haze import config
from haze.jobs import media
from haze.jobs.progress import WhisperProgressParser
from haze.jobs.runtimes.base import (
    DEFAULT_WORK_UNITS,
    JobArgumentError,
    Prepared,
    register,
    safe_join,
)

# An allowlist here is load-bearing well beyond tidiness: WhisperModel's first
# argument accepts a local filesystem path or a Hugging Face repo id, so an
# unvalidated string is both an arbitrary-read and an arbitrary-download
# primitive. Only these names are ever passed through.
# Kept equal to faster_whisper.utils._MODELS, which
# test_whisper_only_allows_models_the_library_knows checks wherever the extra is
# installed. A name here that the library does not know is a job that fails
# after the download rather than at submission.
_MODELS = {
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large", "large-v1", "large-v2", "large-v3",
    "large-v3-turbo", "turbo",
    "distil-small.en", "distil-medium.en",
    "distil-large-v2", "distil-large-v3", "distil-large-v3.5",
}
_DEVICES = {"cpu", "cuda", "auto"}
_COMPUTE_TYPES = {
    "default", "int8", "int8_float16", "int8_bfloat16",
    "float16", "bfloat16", "float32",
}
_FORMATS = {"txt", "srt", "vtt", "json"}

# Whisper's own language set, as a literal. Reading it out of
# faster_whisper.tokenizer would be more authoritative but costs seconds of
# import inside the agent's event loop just to check one argument.
_LANGUAGES = {
    "auto",
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "yue", "zh",
}

MAX_BEAM_SIZE = 10

# Seconds of compute per second of audio, on a node with speed_factor 1.0.
# faster-whisper on CPU runs the small models comfortably faster than realtime
# and the large ones slower, which is the spread that matters: a large-v3 job
# is worth shipping to a GPU machine and a tiny one is not. Keyed on the size
# in the model name so the distil- and .en- variants land in the right bucket
# without enumerating all nineteen of them.
REALTIME_FACTORS = {
    "tiny": 0.05,
    "base": 0.1,
    "small": 0.25,
    "medium": 0.6,
    "turbo": 0.3,
    "large": 1.2,
}
DEFAULT_REALTIME_FACTOR = 0.3


class WhisperRuntime:
    name = "whisper"
    description = (
        "Transcribe speech to text (faster-whisper). The first run on a node "
        "downloads the model -- roughly 150 MB for base, 3 GB for large-v3 -- "
        "and caches it under ~/.haze/models, so later jobs start immediately."
    )

    def available(self) -> bool:
        try:
            return importlib.util.find_spec("faster_whisper") is not None
        except (ImportError, ValueError):
            # A broken or partially-installed package. Absent is the honest
            # answer, and the scheduler will route around this node.
            return False

    def prepare(self, args: dict[str, Any], workdir: Path) -> Prepared:
        # Arguments are validated BEFORE the availability check, which is the one
        # deliberate departure from ffmpeg.py. ffmpeg must resolve its binary
        # first because it needs that path to build an argv; we run
        # sys.executable, which always exists. Validating first means the
        # argument-rejection tests run everywhere, including CI, where this
        # optional extra is absent -- otherwise the tests that matter most would
        # be permanently skipped. Nothing is lost: JobExecutor.submit already
        # refuses an unavailable runtime before prepare() is ever reached.
        audio = args.get("audio")
        if not isinstance(audio, str):
            raise JobArgumentError("`audio` is required")
        # Resolved strictly inside the job directory: the submitter names a file
        # it uploaded, never an arbitrary path on this machine.
        audio_path = safe_join(workdir, audio)
        if not audio_path.is_file():
            raise JobArgumentError(f"{audio!r} was not found in the job's files")

        model = str(args.get("model", "base"))
        if model not in _MODELS:
            raise JobArgumentError(
                f"`model` must be one of {', '.join(sorted(_MODELS))}"
            )

        device = str(args.get("device", "auto")).lower()
        if device not in _DEVICES:
            raise JobArgumentError(f"`device` must be one of {', '.join(sorted(_DEVICES))}")

        compute_type = str(args.get("compute_type", "default")).lower()
        if compute_type not in _COMPUTE_TYPES:
            raise JobArgumentError(
                f"`compute_type` must be one of {', '.join(sorted(_COMPUTE_TYPES))}"
            )

        fmt = str(args.get("format", "txt")).lower()
        if fmt not in _FORMATS:
            raise JobArgumentError(f"`format` must be one of {', '.join(sorted(_FORMATS))}")

        language = str(args.get("language", "auto")).lower()
        if language not in _LANGUAGES:
            raise JobArgumentError(
                "`language` must be a Whisper language code (e.g. en, es, de, ja) "
                "or 'auto' to detect it"
            )

        beam_size = args.get("beam_size", 5)
        # bool is a subclass of int, so `beam_size=True` would otherwise sail
        # through as 1.
        if (
            not isinstance(beam_size, int)
            or isinstance(beam_size, bool)
            or not 1 <= beam_size <= MAX_BEAM_SIZE
        ):
            raise JobArgumentError(f"`beam_size` must be an integer between 1 and {MAX_BEAM_SIZE}")

        vad_filter = args.get("vad_filter", True)
        if not isinstance(vad_filter, bool):
            raise JobArgumentError("`vad_filter` must be true or false")

        if not self.available():
            raise JobArgumentError(
                "faster-whisper is not installed on this node. Install it with "
                "`pip install 'haze-agent[whisper]'`"
            )

        outdir = workdir / "out"
        outdir.mkdir(exist_ok=True)
        output = outdir / f"{audio_path.stem}.{fmt}"

        # Models are large and identical between jobs. Without a stable cache
        # every job re-downloads gigabytes into a directory that is then pruned
        # with the job. Prepared.env is merged over os.environ by the executor.
        cache = config.state_dir() / "models" / "whisper"
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)

        argv = [
            sys.executable, "-m", "haze.jobs.runtimes.whisper",
            "--audio", str(audio_path),
            "--out", str(output),
            "--model", model,
            "--device", device,
            "--compute-type", compute_type,
            "--format", fmt,
            "--language", language,
            "--beam-size", str(beam_size),
            *(["--vad"] if vad_filter else []),
        ]

        return Prepared(
            argv=argv,
            parser=WhisperProgressParser(),
            cwd=workdir,
            env={
                "HF_HOME": str(cache),
                "XDG_CACHE_HOME": str(cache),
                "HF_HUB_DISABLE_TELEMETRY": "1",
                # Otherwise every run prints a paragraph about forking.
                "TOKENIZERS_PARALLELISM": "false",
            },
            explicit_outputs=[output],
        )

    def estimate_work_units(self, args: dict[str, Any], inputs: list[Path]) -> float:
        """Audio duration times a realtime factor for the model size.

        The runtime with the best case for remote placement: a few megabytes of
        audio go out and a few kilobytes of text come back, so the compute term
        decides the placement almost on its own -- which makes the difference
        between a tiny model and large-v3 worth modelling.
        """
        seconds = media.duration_of_named(args.get("audio"), inputs)
        if seconds is None:
            return DEFAULT_WORK_UNITS
        return max(seconds * _realtime_factor(str(args.get("model", "base"))), 0.1)


def _realtime_factor(model: str) -> float:
    """Match a model name to its size bucket, longest name first.

    Longest first because "large-v3-turbo" contains both "large" and "turbo",
    and it is a turbo model -- checking in dictionary order would price it as a
    large one and send a cheap job across the network.
    """
    for size in sorted(REALTIME_FACTORS, key=len, reverse=True):
        if size in model:
            return REALTIME_FACTORS[size]
    return DEFAULT_REALTIME_FACTOR


register(WhisperRuntime())


def _worker(argv: list[str] | None = None) -> int:
    """Transcribe, printing newline-delimited progress.

    The newlines are the whole design. The executor's reader works in whole
    lines and skips over-long ones, so the carriage-return progress bar every
    whisper CLI draws would emit no line at all -- the job would run to
    completion behind a bar that never moved.

    ``choices=`` mirrors the allowlists above. The runtime has already validated
    everything; this is the cheap second layer that keeps the worker safe if it
    is ever invoked directly.
    """
    parser = argparse.ArgumentParser(prog="haze-whisper")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", required=True, choices=sorted(_MODELS))
    parser.add_argument("--device", required=True, choices=sorted(_DEVICES))
    parser.add_argument("--compute-type", required=True, choices=sorted(_COMPUTE_TYPES))
    parser.add_argument("--format", required=True, choices=sorted(_FORMATS))
    parser.add_argument("--language", required=True, choices=sorted(_LANGUAGES))
    parser.add_argument("--beam-size", required=True, type=int, choices=range(1, MAX_BEAM_SIZE + 1))
    parser.add_argument("--vad", action="store_true")
    opts = parser.parse_args(argv)

    # Imported here, not at module scope: this is an optional extra, and the
    # module must import cleanly on a node that does not have it so that
    # available() can report False.
    from faster_whisper import WhisperModel

    model = WhisperModel(opts.model, device=opts.device, compute_type=opts.compute_type)
    segments, info = model.transcribe(
        opts.audio,
        language=None if opts.language == "auto" else opts.language,
        beam_size=opts.beam_size,
        vad_filter=opts.vad,
    )

    # info.duration, not info.duration_after_vad: segment timestamps are in
    # original-audio time, so the VAD-trimmed length would make the bar
    # overshoot 100% on anything with silence in it.
    total = float(getattr(info, "duration", 0.0) or 0.0)
    print(f"duration {total:.2f}", flush=True)

    collected: list[tuple[float, float, str]] = []
    for segment in segments:
        start, end = float(segment.start), float(segment.end)
        # Whisper occasionally emits a newline inside a segment; leaving it in
        # would break the one-fact-per-line protocol the parser relies on.
        text = " ".join(str(segment.text).split())
        collected.append((start, end, text))
        print(f"processed {end:.2f}s / {total:.2f}s", flush=True)
        if text:
            print(f"segment {text[:120]}", flush=True)

    # Written once, at the end. Streaming it would leave a truncated file behind
    # when a job is cancelled or hits its wall clock, and a half-written .srt
    # looks exactly like a complete one to whoever fetches it.
    out = Path(opts.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(opts.format, collected, info), encoding="utf-8")

    print("done", flush=True)
    return 0


def _render(fmt: str, segments: list[tuple[float, float, str]], info: Any) -> str:
    if fmt == "txt":
        return "".join(f"{text}\n" for _, _, text in segments)

    if fmt == "json":
        return json.dumps(
            {
                "language": getattr(info, "language", None),
                "duration": getattr(info, "duration", None),
                "segments": [
                    {"start": start, "end": end, "text": text}
                    for start, end, text in segments
                ],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"

    if fmt == "vtt":
        lines = ["WEBVTT", ""]
        for start, end, text in segments:
            lines += [f"{_timestamp(start, '.')} --> {_timestamp(end, '.')}", text, ""]
        return "\n".join(lines)

    lines = []
    for index, (start, end, text) in enumerate(segments, start=1):
        lines += [str(index), f"{_timestamp(start, ',')} --> {_timestamp(end, ',')}", text, ""]
    return "\n".join(lines)


def _timestamp(seconds: float, decimal_mark: str) -> str:
    """``HH:MM:SS,mmm`` for SubRip, ``HH:MM:SS.mmm`` for WebVTT -- the two
    formats differ in that one character and in nothing else."""
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_mark}{millis:03d}"


if __name__ == "__main__":  # pragma: no cover -- subprocess entrypoint
    sys.exit(_worker())


__all__ = ["WhisperRuntime"]
