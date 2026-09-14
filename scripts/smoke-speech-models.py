#!/usr/bin/env python3
"""Run one isolated sherpa-onnx model smoke and emit one JSON evidence record."""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "model",
        choices=("silero", "whisper", "nemotron", "parakeet", "campplus", "pyannote"),
    )
    parser.add_argument("--inventory", type=Path, default=Path("models_loaded"))
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--language", default="en")
    parser.add_argument("--threads", type=int, default=4)
    return parser.parse_args()


def load_dependencies() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        import sherpa_onnx
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit(
            "Run with: uv run --with sherpa-onnx==1.13.3 --with soundfile "
            "python scripts/smoke-speech-models.py <model>"
        ) from exc
    return np, sherpa_onnx, sf


def rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def default_wav(inventory: Path, model: str) -> Path:
    if model == "parakeet":
        return inventory / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/test_wavs/en.wav"
    return inventory / "sherpa-onnx-whisper-base/test_wavs/0.wav"


def timed_result(
    *,
    model: str,
    runtime: str,
    wav: Path,
    audio: Any,
    sample_rate: int,
    load_started: float,
    load_finished: float,
    inference_finished: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    duration = len(audio) / sample_rate
    inference_seconds = inference_finished - load_finished
    return {
        "model": model,
        "runtime": runtime,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "wav": str(wav),
        "sample_rate": sample_rate,
        "audio_seconds": duration,
        "load_seconds": load_finished - load_started,
        "inference_seconds": inference_seconds,
        "rtf": inference_seconds / duration,
        "max_rss_bytes": rss_bytes(),
        **result,
    }


def smoke_silero(args: argparse.Namespace, np: Any, sherpa: Any, sf: Any) -> dict[str, Any]:
    wav = args.wav or default_wav(args.inventory, args.model)
    audio, sample_rate = sf.read(wav, dtype="float32")
    audio = np.ascontiguousarray(audio)
    config = sherpa.VadModelConfig()
    config.silero_vad.model = str(args.inventory / "silero/silero_vad.onnx")
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_silence_duration = 0.25
    config.silero_vad.min_speech_duration = 0.25
    config.sample_rate = 16_000
    config.num_threads = args.threads
    started = time.perf_counter()
    vad = sherpa.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    loaded = time.perf_counter()
    window = config.silero_vad.window_size
    for offset in range(0, len(audio), window):
        vad.accept_waveform(audio[offset : offset + window])
    vad.flush()
    segments = []
    while not vad.empty():
        segment = vad.front
        segments.append({"start_sample": segment.start, "sample_count": len(segment.samples)})
        vad.pop()
    finished = time.perf_counter()
    return timed_result(
        model=args.model,
        runtime=sherpa.__version__,
        wav=wav,
        audio=audio,
        sample_rate=sample_rate,
        load_started=started,
        load_finished=loaded,
        inference_finished=finished,
        result={"segments": segments},
    )


def smoke_whisper(args: argparse.Namespace, np: Any, sherpa: Any, sf: Any) -> dict[str, Any]:
    root = args.inventory / "sherpa-onnx-whisper-base"
    wav = args.wav or default_wav(args.inventory, args.model)
    audio, sample_rate = sf.read(wav, dtype="float32")
    audio = np.ascontiguousarray(audio)
    started = time.perf_counter()
    recognizer = sherpa.OfflineRecognizer.from_whisper(
        encoder=str(root / "base-encoder.int8.onnx"),
        decoder=str(root / "base-decoder.int8.onnx"),
        tokens=str(root / "base-tokens.txt"),
        language=args.language,
        num_threads=args.threads,
    )
    loaded = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, audio)
    recognizer.decode_stream(stream)
    finished = time.perf_counter()
    return timed_result(
        model=args.model,
        runtime=sherpa.__version__,
        wav=wav,
        audio=audio,
        sample_rate=sample_rate,
        load_started=started,
        load_finished=loaded,
        inference_finished=finished,
        result={"text": stream.result.text},
    )


def smoke_nemotron(args: argparse.Namespace, np: Any, sherpa: Any, sf: Any) -> dict[str, Any]:
    root = args.inventory / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11"
    wav = args.wav or default_wav(args.inventory, args.model)
    audio, sample_rate = sf.read(wav, dtype="float32")
    audio = np.ascontiguousarray(audio)
    started = time.perf_counter()
    recognizer = sherpa.OnlineRecognizer.from_transducer(
        tokens=str(root / "tokens.txt"),
        encoder=str(root / "encoder.int8.onnx"),
        decoder=str(root / "decoder.int8.onnx"),
        joiner=str(root / "joiner.int8.onnx"),
        num_threads=args.threads,
        model_type="nemo_transducer",
    )
    loaded = time.perf_counter()
    stream = recognizer.create_stream()
    stream.set_option("language", args.language)
    stream.accept_waveform(sample_rate, audio)
    stream.input_finished()
    revisions = []
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
        revisions.append(recognizer.get_result(stream))
    finished = time.perf_counter()
    return timed_result(
        model=args.model,
        runtime=sherpa.__version__,
        wav=wav,
        audio=audio,
        sample_rate=sample_rate,
        load_started=started,
        load_finished=loaded,
        inference_finished=finished,
        result={
            "text": recognizer.get_result(stream),
            "revision_count": len(revisions),
            "nonempty_revision_count": sum(bool(value) for value in revisions),
        },
    )


def smoke_parakeet(args: argparse.Namespace, np: Any, sherpa: Any, sf: Any) -> dict[str, Any]:
    root = args.inventory / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    wav = args.wav or default_wav(args.inventory, args.model)
    audio, sample_rate = sf.read(wav, dtype="float32")
    audio = np.ascontiguousarray(audio)
    started = time.perf_counter()
    recognizer = sherpa.OfflineRecognizer.from_transducer(
        tokens=str(root / "tokens.txt"),
        encoder=str(root / "encoder.int8.onnx"),
        decoder=str(root / "decoder.int8.onnx"),
        joiner=str(root / "joiner.int8.onnx"),
        num_threads=args.threads,
        model_type="nemo_transducer",
    )
    loaded = time.perf_counter()
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, audio)
    recognizer.decode_stream(stream)
    finished = time.perf_counter()
    return timed_result(
        model=args.model,
        runtime=sherpa.__version__,
        wav=wav,
        audio=audio,
        sample_rate=sample_rate,
        load_started=started,
        load_finished=loaded,
        inference_finished=finished,
        result={"text": stream.result.text},
    )


def smoke_campplus(args: argparse.Namespace, np: Any, sherpa: Any, sf: Any) -> dict[str, Any]:
    model = args.inventory / "3dspeaker/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
    wav = args.wav or default_wav(args.inventory, args.model)
    audio, sample_rate = sf.read(wav, dtype="float32")
    audio = np.ascontiguousarray(audio)
    started = time.perf_counter()
    config = sherpa.SpeakerEmbeddingExtractorConfig(
        model=str(model), num_threads=args.threads, provider="cpu"
    )
    if not config.validate():
        raise RuntimeError("invalid CAMPPlus configuration")
    extractor = sherpa.SpeakerEmbeddingExtractor(config)
    loaded = time.perf_counter()
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=sample_rate, waveform=audio)
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise RuntimeError("CAMPPlus stream is not ready")
    embedding = np.asarray(extractor.compute(stream))
    finished = time.perf_counter()
    return timed_result(
        model=args.model,
        runtime=sherpa.__version__,
        wav=wav,
        audio=audio,
        sample_rate=sample_rate,
        load_started=started,
        load_finished=loaded,
        inference_finished=finished,
        result={
            "embedding_dimensions": len(embedding),
            "embedding_finite": bool(np.isfinite(embedding).all()),
            "embedding_l2_norm": float(np.linalg.norm(embedding)),
        },
    )


def smoke_pyannote(args: argparse.Namespace, np: Any, sherpa: Any, sf: Any) -> dict[str, Any]:
    segmentation = args.inventory / "sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx"
    embedding = (
        args.inventory / "3dspeaker/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
    )
    wav = args.wav or default_wav(args.inventory, args.model)
    audio, sample_rate = sf.read(wav, dtype="float32")
    audio = np.ascontiguousarray(audio)
    started = time.perf_counter()
    config = sherpa.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
            num_threads=args.threads,
            provider="cpu",
        ),
        embedding=sherpa.SpeakerEmbeddingExtractorConfig(
            model=str(embedding), num_threads=args.threads, provider="cpu"
        ),
        clustering=sherpa.FastClusteringConfig(num_clusters=1),
    )
    if not config.validate():
        raise RuntimeError("invalid Pyannote/CAMPPlus configuration")
    diarizer = sherpa.OfflineSpeakerDiarization(config)
    loaded = time.perf_counter()
    result = diarizer.process(audio)
    finished = time.perf_counter()
    segments = [
        {"start": segment.start, "end": segment.end, "speaker": segment.speaker}
        for segment in result.sort_by_start_time()
    ]
    return timed_result(
        model=args.model,
        runtime=sherpa.__version__,
        wav=wav,
        audio=audio,
        sample_rate=sample_rate,
        load_started=started,
        load_finished=loaded,
        inference_finished=finished,
        result={"speakers": result.num_speakers, "segments": segments},
    )


def main() -> None:
    args = parse_args()
    if args.threads < 1:
        raise SystemExit("--threads must be positive")
    if not args.inventory.is_dir():
        raise SystemExit(f"model inventory does not exist: {args.inventory}")
    np, sherpa, sf = load_dependencies()
    runners = {
        "silero": smoke_silero,
        "whisper": smoke_whisper,
        "nemotron": smoke_nemotron,
        "parakeet": smoke_parakeet,
        "campplus": smoke_campplus,
        "pyannote": smoke_pyannote,
    }
    evidence = runners[args.model](args, np, sherpa, sf)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
