"""Isolated sherpa-onnx speech worker process."""

import argparse
import base64
import binascii
import concurrent.futures
import importlib
import os
import socket
import sys
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from elsewise.speech.worker_protocol import (
    SPEECH_WORKER_PROTOCOL_VERSION,
    SpeechWorkerProtocolError,
    read_worker_message,
    write_worker_message,
)

MAX_STREAMS = 8
MAX_CACHE_ENTRIES = 256
MAX_FRAME_SAMPLES = 3_200
MAX_PENDING_RECOGNITIONS_PER_STREAM = 4


class WorkerFailure(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail[:2_000]


@dataclass(frozen=True, slots=True)
class RecognitionHypothesis:
    text: str
    durable: bool


class SherpaOnnxStream:
    def __init__(
        self,
        *,
        sherpa: Any,
        numpy: Any,
        profile: str,
        recognizer: Any,
        finalizer: Any | None,
        executor: concurrent.futures.ThreadPoolExecutor,
        silero_model: Path,
        language: str,
        threads: int,
    ) -> None:
        self.sherpa = sherpa
        self.numpy = numpy
        self.profile = profile
        self.recognizer = recognizer
        self.finalizer = finalizer
        self.executor = executor
        self.silero_model = silero_model
        self.language = language
        self.threads = threads
        self.vad = self._new_vad()
        self.vad_origin = 0
        self.expected_sequence: int | None = None
        self.expected_sample_position: int | None = None
        self.pending: list[
            tuple[
                concurrent.futures.Future[tuple[RecognitionHypothesis, ...]],
                int,
                int,
            ]
        ] = []

    def push(self, message: Mapping[str, Any]) -> list[dict[str, Any]]:
        sequence = bounded_integer(message, "sequence", maximum=2**64 - 1)
        sample_position = bounded_integer(message, "source_sample_position", maximum=2**64 - 1)
        frame_samples = bounded_integer(message, "frame_samples", maximum=MAX_FRAME_SAMPLES)
        flags = bounded_integer(message, "flags", maximum=0b111)
        encoded_pcm = message.get("pcm_base64")
        if not isinstance(encoded_pcm, str):
            raise WorkerFailure("invalid_audio_frame", "pcm_base64 must be a string")
        try:
            pcm = base64.b64decode(encoded_pcm, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise WorkerFailure("invalid_audio_frame", "pcm_base64 is invalid") from exc
        if len(pcm) != frame_samples * 4:
            raise WorkerFailure("invalid_audio_frame", "PCM length does not match frame_samples")

        events = self._collect_recognitions(block=False)
        discontinuity = bool(flags & 0b11)
        if self.expected_sequence is not None and (
            sequence != self.expected_sequence or sample_position != self.expected_sample_position
        ):
            if not discontinuity:
                raise WorkerFailure(
                    "audio_discontinuity",
                    "audio continuity changed without a discontinuity flag",
                )
            events.extend(self.flush())
            self.vad_origin = sample_position
        elif self.expected_sequence is None:
            self.vad_origin = sample_position

        audio = self.numpy.frombuffer(pcm, dtype="<f4")
        self.vad.accept_waveform(audio)
        self._schedule_segments()
        events.extend(self._collect_recognitions(block=False))
        self.expected_sequence = sequence + 1
        self.expected_sample_position = sample_position + frame_samples
        if flags & 0b100:
            events.extend(self.flush())
        return events

    def flush(self) -> list[dict[str, Any]]:
        self.vad.flush()
        self._schedule_segments()
        events = self._collect_recognitions(block=True)
        self.vad = self._new_vad()
        if self.expected_sample_position is not None:
            self.vad_origin = self.expected_sample_position
        return events

    def _new_vad(self) -> Any:
        config = self.sherpa.VadModelConfig()
        config.silero_vad.model = str(self.silero_model)
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_silence_duration = 0.25
        config.silero_vad.min_speech_duration = 0.25
        config.sample_rate = 16_000
        config.num_threads = self.threads
        return self.sherpa.VoiceActivityDetector(config, buffer_size_in_seconds=60)

    def _schedule_segments(self) -> None:
        while not self.vad.empty():
            if len(self.pending) >= MAX_PENDING_RECOGNITIONS_PER_STREAM:
                raise WorkerFailure("asr_overloaded", "speech recognition queue is full")
            segment = self.vad.front
            samples = self.numpy.ascontiguousarray(segment.samples, dtype=self.numpy.float32)
            first_sample = self.vad_origin + int(segment.start)
            self.vad.pop()
            self.pending.append(
                (
                    self.executor.submit(self._recognize, samples),
                    first_sample,
                    first_sample + len(samples),
                )
            )

    def _collect_recognitions(self, *, block: bool) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while self.pending and (block or self.pending[0][0].done()):
            future, first_sample, last_sample = self.pending.pop(0)
            hypotheses = tuple(
                hypothesis for hypothesis in future.result() if hypothesis.text.strip()
            )
            if not hypotheses:
                continue
            utterance_id = str(uuid4())
            for revision, hypothesis in enumerate(hypotheses, start=1):
                events.append(
                    {
                        "utterance_id": utterance_id,
                        "revision": revision,
                        "kind": "final" if hypothesis.durable else "partial",
                        "text": hypothesis.text.strip(),
                        "first_sample_position": first_sample,
                        "last_sample_position": last_sample,
                        "confidence": None,
                        "durable": hypothesis.durable,
                    }
                )
        return events

    def _recognize(self, samples: Any) -> tuple[RecognitionHypothesis, ...]:
        if self.profile == "conservative":
            text = self._recognize_offline(self.recognizer, samples)
            return (RecognitionHypothesis(text, True),) if text else ()

        live_text = self._recognize_online(samples)
        if self.profile == "standard":
            return (RecognitionHypothesis(live_text, True),) if live_text else ()

        final_text = (
            self._recognize_offline(self.finalizer, samples) if self.finalizer is not None else ""
        )
        if live_text and final_text and live_text != final_text:
            return (
                RecognitionHypothesis(live_text, False),
                RecognitionHypothesis(final_text, True),
            )
        text = final_text or live_text
        return (RecognitionHypothesis(text, True),) if text else ()

    @staticmethod
    def _recognize_offline(recognizer: Any, samples: Any) -> str:
        recognition_stream = recognizer.create_stream()
        recognition_stream.accept_waveform(16_000, samples)
        recognizer.decode_stream(recognition_stream)
        return str(recognition_stream.result.text).strip()

    def _recognize_online(self, samples: Any) -> str:
        recognition_stream = self.recognizer.create_stream()
        recognition_stream.set_option("language", self.language)
        recognition_stream.accept_waveform(16_000, samples)
        recognition_stream.input_finished()
        while self.recognizer.is_ready(recognition_stream):
            self.recognizer.decode_stream(recognition_stream)
        return str(self.recognizer.get_result(recognition_stream)).strip()


class WorkerRuntime:
    def __init__(self) -> None:
        self.streams: dict[str, SherpaOnnxStream] = {}
        self.recognizers: dict[tuple[str, str, str, int], Any] = {}
        self.sherpa: Any | None = None
        self.numpy: Any | None = None
        # Keep the shared recognizer serialized without blocking control IPC.
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="elsewise-asr"
        )

    def create_stream(self, message: Mapping[str, Any]) -> None:
        stream_id = bounded_string(message, "stream_id", maximum=128)
        if stream_id in self.streams:
            raise WorkerFailure("stream_exists", "speech stream is already running")
        if len(self.streams) >= MAX_STREAMS:
            raise WorkerFailure("stream_limit", "speech stream limit reached")
        profile = bounded_string(message, "profile", maximum=32)
        if profile not in {"conservative", "standard", "best"}:
            raise WorkerFailure("invalid_profile", "speech profile is invalid")
        language = bounded_string(message, "language", maximum=32)
        threads = bounded_integer(message, "threads", minimum=1, maximum=32)
        model_root = Path(bounded_string(message, "model_root", maximum=1_024)).resolve()
        silero_model = Path(bounded_string(message, "silero_model", maximum=1_024)).resolve()
        finalizer_value = message.get("finalizer_root")
        if finalizer_value is not None and not isinstance(finalizer_value, str):
            raise WorkerFailure("invalid_field", "finalizer_root must be a string or null")
        finalizer_root = Path(finalizer_value).resolve() if finalizer_value else None
        required = (silero_model, *self._model_files(model_root, profile == "conservative"))
        if profile == "best":
            if finalizer_root is None:
                raise WorkerFailure("model_missing", "best profile finalizer is missing")
            required = (*required, *self._model_files(finalizer_root, False))
        if not all(path.is_file() for path in required):
            raise WorkerFailure("model_missing", "required speech model files are missing")
        sherpa, numpy = self._dependencies()
        model_kind = "whisper" if profile == "conservative" else "nemotron"
        recognizer = self._recognizer(
            sherpa, model_kind, model_root, language=language, threads=threads
        )
        finalizer = (
            self._recognizer(
                sherpa,
                "parakeet",
                finalizer_root,
                language=language,
                threads=threads,
            )
            if finalizer_root is not None
            else None
        )
        self.streams[stream_id] = SherpaOnnxStream(
            sherpa=sherpa,
            numpy=numpy,
            profile=profile,
            recognizer=recognizer,
            finalizer=finalizer,
            executor=self.executor,
            silero_model=silero_model,
            language=language,
            threads=threads,
        )

    @staticmethod
    def _model_files(root: Path, whisper: bool) -> tuple[Path, ...]:
        if whisper:
            return (
                root / "base-encoder.int8.onnx",
                root / "base-decoder.int8.onnx",
                root / "base-tokens.txt",
            )
        return (
            root / "encoder.int8.onnx",
            root / "decoder.int8.onnx",
            root / "joiner.int8.onnx",
            root / "tokens.txt",
        )

    def _recognizer(
        self,
        sherpa: Any,
        kind: str,
        root: Path,
        *,
        language: str,
        threads: int,
    ) -> Any:
        cache_key = (kind, str(root), language, threads)
        recognizer = self.recognizers.get(cache_key)
        if recognizer is not None:
            return recognizer
        if kind == "whisper":
            recognizer = sherpa.OfflineRecognizer.from_whisper(
                encoder=str(root / "base-encoder.int8.onnx"),
                decoder=str(root / "base-decoder.int8.onnx"),
                tokens=str(root / "base-tokens.txt"),
                language=language,
                num_threads=threads,
            )
        elif kind == "nemotron":
            recognizer = sherpa.OnlineRecognizer.from_transducer(
                tokens=str(root / "tokens.txt"),
                encoder=str(root / "encoder.int8.onnx"),
                decoder=str(root / "decoder.int8.onnx"),
                joiner=str(root / "joiner.int8.onnx"),
                num_threads=threads,
                model_type="nemo_transducer",
            )
        else:
            recognizer = sherpa.OfflineRecognizer.from_transducer(
                tokens=str(root / "tokens.txt"),
                encoder=str(root / "encoder.int8.onnx"),
                decoder=str(root / "decoder.int8.onnx"),
                joiner=str(root / "joiner.int8.onnx"),
                num_threads=threads,
                model_type="nemo_transducer",
            )
        self.recognizers[cache_key] = recognizer
        return recognizer

    def push(self, message: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self._stream(message).push(message)

    def flush(self, message: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self._stream(message).flush()

    def close_stream(self, message: Mapping[str, Any]) -> bool:
        stream_id = bounded_string(message, "stream_id", maximum=128)
        return self.streams.pop(stream_id, None) is not None

    def close(self) -> None:
        self.streams.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _stream(self, message: Mapping[str, Any]) -> SherpaOnnxStream:
        stream_id = bounded_string(message, "stream_id", maximum=128)
        stream = self.streams.get(stream_id)
        if stream is None:
            raise WorkerFailure("stream_missing", "speech stream is not running")
        return stream

    def _dependencies(self) -> tuple[Any, Any]:
        if self.sherpa is None:
            try:
                self.sherpa = importlib.import_module("sherpa_onnx")
                self.numpy = importlib.import_module("numpy")
            except ImportError as exc:
                raise WorkerFailure(
                    "runtime_missing", "sherpa-onnx runtime is not installed"
                ) from exc
        return self.sherpa, self.numpy


def serve(socket_path: Path) -> int:
    if os.name == "nt":
        raise WorkerFailure("unsupported_transport", "Windows speech transport is deferred")
    validate_socket_path(socket_path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    runtime: WorkerRuntime | None = None
    try:
        listener.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        listener.listen(1)
        connection, _ = listener.accept()
        with connection:
            reader = connection.makefile("rb")
            writer = connection.makefile("wb")
            runtime = WorkerRuntime()
            write_worker_message(
                writer,
                {
                    "type": "worker.hello",
                    "protocol_version": SPEECH_WORKER_PROTOCOL_VERSION,
                    "worker_instance_id": str(uuid4()),
                    "runtime": "sherpa-onnx",
                },
            )
            ready = False
            cache: OrderedDict[str, tuple[dict[str, Any], dict[str, Any]]] = OrderedDict()
            while True:
                message = read_worker_message(reader)
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    write_worker_message(
                        writer, error_response("", "invalid_request", "request_id is required")
                    )
                    continue
                plain_message = dict(message)
                cached = cache.get(request_id)
                if cached is not None:
                    known_request, response = cached
                    if known_request != plain_message:
                        response = error_response(
                            request_id,
                            "request_id_conflict",
                            "request_id was reused with a different payload",
                        )
                    write_worker_message(writer, response)
                    continue
                try:
                    response, ready, shutdown = handle_message(runtime, message, ready)
                except WorkerFailure as error:
                    response = error_response(request_id, error.code, error.detail)
                    shutdown = False
                except Exception as error:  # Keep one stream failure inside the worker boundary.
                    stream_id = message.get("stream_id")
                    if isinstance(stream_id, str):
                        runtime.streams.pop(stream_id, None)
                    response = error_response(
                        request_id,
                        "runtime_failed",
                        f"{type(error).__name__}: {error}",
                    )
                    shutdown = False
                response["request_id"] = request_id
                cache[request_id] = (plain_message, response)
                if len(cache) > MAX_CACHE_ENTRIES:
                    cache.popitem(last=False)
                write_worker_message(writer, response)
                if shutdown:
                    return 0
    except (OSError, SpeechWorkerProtocolError) as error:
        raise WorkerFailure("worker_io_failed", str(error)) from error
    finally:
        if runtime is not None:
            runtime.close()
        listener.close()
        socket_path.unlink(missing_ok=True)


def handle_message(
    runtime: WorkerRuntime, message: Mapping[str, Any], ready: bool
) -> tuple[dict[str, Any], bool, bool]:
    message_type = message.get("type")
    if message_type == "daemon.hello":
        return (
            {
                "type": "worker.ready",
                "protocol_version": SPEECH_WORKER_PROTOCOL_VERSION,
                "runtime": "sherpa-onnx",
            },
            True,
            False,
        )
    if not ready:
        raise WorkerFailure("not_ready", "worker handshake is incomplete")
    if message_type == "stream.create":
        runtime.create_stream(message)
        return (base_response("stream.created"), ready, False)
    if message_type == "audio.push":
        return (
            {**base_response("audio.result"), "events": runtime.push(message)},
            ready,
            False,
        )
    if message_type == "stream.flush":
        return (
            {**base_response("stream.flushed"), "events": runtime.flush(message)},
            ready,
            False,
        )
    if message_type == "stream.close":
        return (
            {
                **base_response("stream.closed"),
                "was_running": runtime.close_stream(message),
            },
            ready,
            False,
        )
    if message_type == "worker.health":
        return (
            {
                **base_response("worker.health_result"),
                "status": "ready",
                "active_streams": len(runtime.streams),
                "loaded_recognizers": len(runtime.recognizers),
            },
            ready,
            False,
        )
    if message_type == "worker.shutdown":
        runtime.streams.clear()
        return (base_response("worker.shutdown_ack"), ready, True)
    raise WorkerFailure("invalid_command", "command is invalid in the current worker state")


def base_response(message_type: str) -> dict[str, Any]:
    return {"type": message_type, "protocol_version": SPEECH_WORKER_PROTOCOL_VERSION}


def error_response(request_id: str, code: str, detail: str) -> dict[str, Any]:
    return {
        "type": "worker.error",
        "protocol_version": SPEECH_WORKER_PROTOCOL_VERSION,
        "request_id": request_id,
        "code": code,
        "detail": detail[:2_000],
    }


def bounded_string(message: Mapping[str, Any], field: str, *, maximum: int) -> str:
    value = message.get(field)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WorkerFailure("invalid_request", f"{field} is invalid")
    return value


def bounded_integer(
    message: Mapping[str, Any],
    field: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> int:
    value = message.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise WorkerFailure("invalid_request", f"{field} is invalid")
    return value


def validate_socket_path(socket_path: Path) -> None:
    if socket_path.exists():
        raise WorkerFailure("invalid_socket", "speech worker socket already exists")
    parent = socket_path.parent
    if not parent.is_dir():
        raise WorkerFailure("invalid_socket", "speech worker socket parent is missing")
    if parent.stat().st_mode & 0o077:
        raise WorkerFailure("invalid_socket", "speech worker socket parent is not private")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--socket", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.serve or args.socket is None:
        print("use --serve --socket <path>", file=sys.stderr)
        return 2
    try:
        return serve(args.socket)
    except WorkerFailure as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
