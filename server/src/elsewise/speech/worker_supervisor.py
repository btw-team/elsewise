import asyncio
import base64
import contextlib
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from elsewise.audio.protocol import AudioFrame
from elsewise.speech.contracts import SpeechEvent
from elsewise.speech.worker_protocol import (
    SPEECH_CONTROL_HEADER_BYTES,
    SPEECH_WORKER_PROTOCOL_VERSION,
    SpeechWorkerProtocolError,
    decode_worker_message,
    encode_worker_message,
    worker_payload_bytes_from_header,
)

WORKER_START_TIMEOUT_SECONDS = 10.0
WORKER_REQUEST_TIMEOUT_SECONDS = 120.0
WORKER_STOP_TIMEOUT_SECONDS = 3.0
MAX_WORKER_DIAGNOSTIC_BYTES = 16 * 1024


class SpeechWorkerError(RuntimeError):
    pass


class SpeechWorkerSupervisor:
    def __init__(self, command: Sequence[str] | None = None) -> None:
        self.command = tuple(command or resolve_speech_worker_command())
        if not self.command:
            raise ValueError("speech worker command must not be empty")
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._socket_directory: Path | None = None
        self._worker_instance_id: str | None = None
        self._state_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self.running and self._process is not None else None

    @property
    def worker_instance_id(self) -> str | None:
        return self._worker_instance_id

    @property
    def socket_directory(self) -> Path | None:
        return self._socket_directory

    async def start(self) -> None:
        if os.name == "nt":
            raise SpeechWorkerError("speech worker local IPC is not implemented on Windows")
        async with self._state_lock:
            if self.running:
                return
            await self._cleanup_connection()
            self._cleanup_socket_directory()
            self._socket_directory = Path(tempfile.mkdtemp(prefix="elsewise-speech-", dir="/tmp"))
            socket_path = self._socket_directory / "worker.sock"
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command,
                    "--serve",
                    "--socket",
                    str(socket_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                await self._wait_for_socket(socket_path)
                self._reader, self._writer = await asyncio.open_unix_connection(socket_path)
                hello = await asyncio.wait_for(
                    self._read_message(), timeout=WORKER_START_TIMEOUT_SECONDS
                )
                if hello.get("type") != "worker.hello" or hello.get("runtime") != "sherpa-onnx":
                    raise SpeechWorkerError("speech worker handshake is invalid")
                worker_instance_id = hello.get("worker_instance_id")
                if not isinstance(worker_instance_id, str) or not worker_instance_id:
                    raise SpeechWorkerError("speech worker instance ID is invalid")
                self._worker_instance_id = worker_instance_id
                await self._request_unlocked({"type": "daemon.hello"}, expected_type="worker.ready")
            except BaseException:
                await self._abort_start()
                raise

    async def create_stream(
        self,
        *,
        stream_id: str,
        profile: str,
        language: str,
        model_root: Path,
        silero_model: Path,
        finalizer_root: Path | None,
        threads: int,
    ) -> None:
        await self.start()
        await self._request(
            {
                "type": "stream.create",
                "stream_id": stream_id,
                "profile": profile,
                "language": language,
                "model_root": str(model_root.resolve()),
                "silero_model": str(silero_model.resolve()),
                "finalizer_root": (
                    str(finalizer_root.resolve()) if finalizer_root is not None else None
                ),
                "threads": threads,
            },
            expected_type="stream.created",
        )

    async def push_audio(self, stream_id: str, frame: AudioFrame) -> tuple[SpeechEvent, ...]:
        response = await self._request(
            {
                "type": "audio.push",
                "stream_id": stream_id,
                "sequence": frame.sequence,
                "source_sample_position": frame.source_sample_position,
                "frame_samples": frame.frame_samples,
                "flags": int(frame.flags),
                "pcm_base64": base64.b64encode(frame.pcm).decode("ascii"),
            },
            expected_type="audio.result",
        )
        return parse_events(response)

    async def flush_stream(self, stream_id: str) -> tuple[SpeechEvent, ...]:
        response = await self._request(
            {"type": "stream.flush", "stream_id": stream_id},
            expected_type="stream.flushed",
        )
        return parse_events(response)

    async def close_stream(self, stream_id: str) -> None:
        await self._request(
            {"type": "stream.close", "stream_id": stream_id},
            expected_type="stream.closed",
        )

    async def health(self) -> Mapping[str, Any]:
        return await self._request({"type": "worker.health"}, expected_type="worker.health_result")

    async def restart(
        self, *, maximum_attempts: int = 3, initial_backoff_seconds: float = 0.05
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must not be negative")
        await self.close()
        last_error: BaseException | None = None
        for attempt in range(maximum_attempts):
            try:
                await self.start()
                return
            except (OSError, SpeechWorkerError) as error:
                last_error = error
                if attempt + 1 < maximum_attempts:
                    await asyncio.sleep(initial_backoff_seconds * (2**attempt))
        raise SpeechWorkerError("speech worker restart attempts exhausted") from last_error

    async def close(self) -> None:
        async with self._state_lock:
            process = self._process
            if process is not None and process.returncode is None and self._writer is not None:
                with contextlib.suppress(SpeechWorkerError, TimeoutError):
                    await asyncio.wait_for(
                        self._request_unlocked(
                            {"type": "worker.shutdown"},
                            expected_type="worker.shutdown_ack",
                        ),
                        timeout=WORKER_STOP_TIMEOUT_SECONDS,
                    )
            await self._cleanup_connection()
            if process is not None and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=WORKER_STOP_TIMEOUT_SECONDS)
                except TimeoutError:
                    await self._terminate(process)
            self._process = None
            self._worker_instance_id = None
            self._cleanup_socket_directory()

    async def _request(
        self, message: Mapping[str, Any], *, expected_type: str
    ) -> Mapping[str, Any]:
        if not self.running:
            raise SpeechWorkerError("speech worker is not running")
        async with self._request_lock:
            return await asyncio.wait_for(
                self._request_unlocked(message, expected_type=expected_type),
                timeout=WORKER_REQUEST_TIMEOUT_SECONDS,
            )

    async def _request_unlocked(
        self, message: Mapping[str, Any], *, expected_type: str
    ) -> Mapping[str, Any]:
        if self._writer is None:
            raise SpeechWorkerError("speech worker connection is unavailable")
        outgoing = dict(message)
        outgoing["protocol_version"] = SPEECH_WORKER_PROTOCOL_VERSION
        outgoing["request_id"] = str(uuid4())
        try:
            self._writer.write(encode_worker_message(outgoing))
            await self._writer.drain()
            response = await self._read_message()
        except (ConnectionError, asyncio.IncompleteReadError, SpeechWorkerProtocolError) as exc:
            await asyncio.sleep(0)
            process = self._process
            if process is not None and process.returncode is not None:
                stderr = await self._read_stderr(process)
                detail = self._safe_error(
                    f"speech worker exited with code {process.returncode}", stderr
                )
            else:
                detail = "speech worker connection failed"
            raise SpeechWorkerError(detail) from exc
        if response.get("request_id") != outgoing["request_id"]:
            raise SpeechWorkerError("speech worker response request_id mismatch")
        if response.get("type") == "worker.error":
            raise SpeechWorkerError(
                f"{response.get('code', 'worker_error')}: "
                f"{response.get('detail', 'speech worker rejected the command')}"
            )
        if response.get("type") != expected_type:
            raise SpeechWorkerError("speech worker returned an unexpected response")
        return response

    async def _read_message(self) -> Mapping[str, Any]:
        if self._reader is None:
            raise SpeechWorkerError("speech worker connection is unavailable")
        header = await self._reader.readexactly(SPEECH_CONTROL_HEADER_BYTES)
        payload_size = worker_payload_bytes_from_header(header)
        payload = await self._reader.readexactly(payload_size)
        return decode_worker_message(header + payload)

    async def _wait_for_socket(self, socket_path: Path) -> None:
        deadline = asyncio.get_running_loop().time() + WORKER_START_TIMEOUT_SECONDS
        while not socket_path.exists():
            process = self._process
            if process is None or process.returncode is not None:
                stderr = b"" if process is None else await self._read_stderr(process)
                raise SpeechWorkerError(self._safe_error("speech worker failed to start", stderr))
            if asyncio.get_running_loop().time() >= deadline:
                raise SpeechWorkerError("speech worker socket startup timed out")
            await asyncio.sleep(0.01)

    async def _abort_start(self) -> None:
        await self._cleanup_connection()
        process = self._process
        if process is not None and process.returncode is None:
            await self._terminate(process)
        self._process = None
        self._worker_instance_id = None
        self._cleanup_socket_directory()

    async def _cleanup_connection(self) -> None:
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await self._writer.wait_closed()
        self._reader = None
        self._writer = None

    def _cleanup_socket_directory(self) -> None:
        if self._socket_directory is not None:
            shutil.rmtree(self._socket_directory, ignore_errors=True)
            self._socket_directory = None

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=WORKER_STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            await process.wait()

    @staticmethod
    async def _read_stderr(process: asyncio.subprocess.Process) -> bytes:
        if process.stderr is None:
            return b""
        return await process.stderr.read(MAX_WORKER_DIAGNOSTIC_BYTES + 1)

    @staticmethod
    def _safe_error(prefix: str, stderr: bytes) -> str:
        detail = stderr[:MAX_WORKER_DIAGNOSTIC_BYTES].decode("utf-8", errors="replace").strip()
        return f"{prefix}: {detail}" if detail else prefix


def parse_events(response: Mapping[str, Any]) -> tuple[SpeechEvent, ...]:
    raw_events = response.get("events")
    if not isinstance(raw_events, list):
        raise SpeechWorkerError("speech worker events payload is invalid")
    events: list[SpeechEvent] = []
    try:
        for raw in raw_events:
            if not isinstance(raw, dict):
                raise TypeError
            confidence = raw.get("confidence")
            events.append(
                SpeechEvent(
                    utterance_id=str(raw["utterance_id"]),
                    revision=int(raw["revision"]),
                    kind=raw["kind"],
                    text=str(raw["text"]),
                    first_sample_position=int(raw["first_sample_position"]),
                    last_sample_position=int(raw["last_sample_position"]),
                    confidence=None if confidence is None else float(confidence),
                    durable=bool(raw["durable"]),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise SpeechWorkerError("speech worker event is invalid") from exc
    return tuple(events)


def resolve_speech_worker_command() -> tuple[str, ...]:
    suffix = ".exe" if os.name == "nt" else ""
    packaged = Path(sys.executable).resolve().parent / f"elsewise-speech-worker{suffix}"
    if packaged.is_file():
        return (str(packaged),)
    return (sys.executable, "-m", "elsewise.speech.worker_process")
