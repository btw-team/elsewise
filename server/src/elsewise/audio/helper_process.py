import asyncio
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from elsewise.audio.protocol import (
    AUDIO_HEADER_BYTES,
    AUDIO_PROTOCOL_VERSION,
    CONTROL_HEADER_BYTES,
    AudioFrame,
    AudioProtocolError,
    audio_payload_bytes_from_header,
    control_payload_bytes_from_header,
    decode_audio_frame,
    decode_control_frame,
    encode_control_frame,
)

HELPER_PROBE_TIMEOUT_SECONDS = 5.0
HELPER_START_TIMEOUT_SECONDS = 5.0
HELPER_REQUEST_TIMEOUT_SECONDS = 5.0
HELPER_STOP_TIMEOUT_SECONDS = 2.0
MAX_HELPER_DIAGNOSTIC_BYTES = 16 * 1024


def resolve_audio_helper() -> Path:
    executable_name = "elsewise-audio.exe" if os.name == "nt" else "elsewise-audio"
    packaged = Path(__file__).resolve().parents[1] / "bin" / executable_name
    if packaged.is_file():
        return packaged
    repository_root = Path(__file__).resolve().parents[4]
    for profile in ("release", "debug"):
        candidate = repository_root / "target" / profile / executable_name
        if candidate.is_file():
            return candidate
    executable_directory = Path(sys.executable).resolve().parent
    return executable_directory / "elsewise" / "bin" / executable_name


class AudioHelperError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioHelperDescriptor:
    version: str
    protocol_version: int
    canonical_sample_rate: int
    canonical_channels: int
    canonical_sample_format: str
    capabilities: tuple[str, ...]


class AudioHelperSupervisor:
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self._process: asyncio.subprocess.Process | None = None
        self._control_reader: asyncio.StreamReader | None = None
        self._control_writer: asyncio.StreamWriter | None = None
        self._data_reader: asyncio.StreamReader | None = None
        self._data_writer: asyncio.StreamWriter | None = None
        self._socket_directory: Path | None = None
        self._state_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._data_lock = asyncio.Lock()
        self._helper_instance_id: UUID | None = None
        self._clock_offset_ns: int | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def helper_instance_id(self) -> UUID | None:
        return self._helper_instance_id

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None and self.running else None

    @property
    def clock_offset_ns(self) -> int | None:
        """Approximate daemon_monotonic_ns - helper_monotonic_ns from the handshake."""
        return self._clock_offset_ns

    @property
    def socket_directory(self) -> Path | None:
        return self._socket_directory

    async def probe(self) -> AudioHelperDescriptor:
        process = await self._spawn("--describe")
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=HELPER_PROBE_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            await self._terminate(process)
            raise AudioHelperError("helper probe timed out") from exc
        if process.returncode != 0:
            raise AudioHelperError(self._safe_error("helper probe failed", stderr))
        if len(stdout) > MAX_HELPER_DIAGNOSTIC_BYTES:
            raise AudioHelperError("helper descriptor exceeds the protocol bound")
        try:
            raw: Any = json.loads(stdout)
            if not isinstance(raw, dict):
                raise TypeError
            descriptor = AudioHelperDescriptor(
                version=str(raw["version"]),
                protocol_version=int(raw["protocol_version"]),
                canonical_sample_rate=int(raw["canonical_sample_rate"]),
                canonical_channels=int(raw["canonical_channels"]),
                canonical_sample_format=str(raw["canonical_sample_format"]),
                capabilities=tuple(str(item) for item in raw["capabilities"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AudioHelperError("helper returned an invalid descriptor") from exc
        self._validate_descriptor(descriptor)
        return descriptor

    async def start(self) -> None:
        if os.name == "nt":
            raise AudioHelperError("audio helper local IPC is not implemented on Windows")
        async with self._state_lock:
            if self.running:
                return
            await self._cleanup_connections()
            self._cleanup_socket_directory()
            socket_root = Path("/tmp")
            self._socket_directory = Path(
                tempfile.mkdtemp(prefix="elsewise-audio-", dir=socket_root)
            )
            control_path = self._socket_directory / "control.sock"
            data_path = self._socket_directory / "data.sock"
            process = await self._spawn(
                "--serve",
                "--control-socket",
                str(control_path),
                "--data-socket",
                str(data_path),
            )
            self._process = process
            try:
                await self._wait_for_socket(control_path)
                control_reader, control_writer = await asyncio.open_unix_connection(control_path)
                data_reader, data_writer = await asyncio.open_unix_connection(data_path)
                self._control_reader = control_reader
                self._control_writer = control_writer
                self._data_reader = data_reader
                self._data_writer = data_writer

                hello = await asyncio.wait_for(
                    self._read_control(), timeout=HELPER_START_TIMEOUT_SECONDS
                )
                if hello.get("type") != "helper.hello":
                    raise AudioHelperError("helper did not send the expected handshake")
                try:
                    self._helper_instance_id = UUID(str(hello["helper_instance_id"]))
                    capabilities = tuple(str(item) for item in hello["capabilities"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise AudioHelperError("helper returned an invalid handshake") from exc
                if "multi_stream" not in capabilities or "unix_socket_ipc" not in capabilities:
                    raise AudioHelperError("helper local IPC capability mismatch")

                before_ns = time.monotonic_ns()
                response = await self._request_unlocked(
                    {
                        "type": "daemon.hello",
                        "daemon_instance_id": str(uuid4()),
                        "daemon_monotonic_ns": before_ns,
                    },
                    expected_type="helper.ready",
                )
                after_ns = time.monotonic_ns()
                if response.get("echo_daemon_monotonic_ns") != before_ns:
                    raise AudioHelperError("helper clock handshake mismatch")
                helper_ns = response.get("helper_monotonic_ns")
                if not isinstance(helper_ns, int) or helper_ns < 0:
                    raise AudioHelperError("helper returned an invalid monotonic clock")
                self._clock_offset_ns = ((before_ns + after_ns) // 2) - helper_ns
            except BaseException:
                await self._abort_start()
                raise

    async def start_synthetic_source(
        self,
        *,
        source_id: UUID,
        epoch_id: UUID,
        frame_count: int,
        request_id: str | None = None,
    ) -> Mapping[str, Any]:
        if not 1 <= frame_count <= 100_000:
            raise ValueError("frame_count must be between 1 and 100000")
        await self.start()
        return await self._request(
            {
                "type": "source.start",
                "source_kind": "synthetic_audio",
                "source_id": str(source_id),
                "epoch_id": str(epoch_id),
                "frame_count": frame_count,
            },
            expected_type="source.started",
            request_id=request_id,
        )

    async def start_native_source(
        self,
        *,
        source_kind: Literal["native_microphone", "native_process_audio", "native_system_audio"],
        source_id: UUID,
        epoch_id: UUID,
        target_key: str = "default",
        request_id: str | None = None,
    ) -> Mapping[str, Any]:
        if source_kind not in {
            "native_microphone",
            "native_process_audio",
            "native_system_audio",
        }:
            raise ValueError("source_kind is not a supported native audio source")
        if not target_key or len(target_key) > 512:
            raise ValueError("target_key must contain between 1 and 512 characters")
        await self.start()
        return await self._request(
            {
                "type": "source.start",
                "source_kind": source_kind,
                "source_id": str(source_id),
                "epoch_id": str(epoch_id),
                "target_key": target_key,
            },
            expected_type="source.started",
            request_id=request_id,
        )

    async def stop_source(
        self, source_id: UUID, *, request_id: str | None = None
    ) -> Mapping[str, Any]:
        return await self._request(
            {"type": "source.stop", "source_id": str(source_id)},
            expected_type="source.stopped",
            request_id=request_id,
        )

    async def health(self) -> Mapping[str, Any]:
        return await self._request({"type": "helper.health"}, expected_type="helper.health_result")

    async def read_frame(self) -> AudioFrame:
        if not self.running or self._data_reader is None:
            raise AudioHelperError("audio helper is not running")
        async with self._data_lock:
            try:
                header = await self._data_reader.readexactly(AUDIO_HEADER_BYTES)
                payload_bytes = audio_payload_bytes_from_header(header)
                payload = await self._data_reader.readexactly(payload_bytes)
            except asyncio.IncompleteReadError as exc:
                raise AudioHelperError("helper returned a truncated audio stream") from exc
            except AudioProtocolError as exc:
                raise AudioHelperError(str(exc)) from exc
            try:
                return decode_audio_frame(header + payload)
            except AudioProtocolError as exc:
                raise AudioHelperError(str(exc)) from exc

    async def synthetic_frames(
        self,
        *,
        source_id: UUID,
        epoch_id: UUID,
        frame_count: int,
    ) -> AsyncIterator[AudioFrame]:
        await self.start_synthetic_source(
            source_id=source_id,
            epoch_id=epoch_id,
            frame_count=frame_count,
        )
        try:
            for _ in range(frame_count):
                frame = await self.read_frame()
                if frame.source_id != source_id or frame.epoch_id != epoch_id:
                    raise AudioHelperError("helper returned a frame for another stream")
                yield frame
        finally:
            await self.close()

    async def list_sources(self) -> tuple[Mapping[str, Any], ...]:
        response = await self._request({"type": "source.list"}, expected_type="source.list_result")
        sources = response.get("sources")
        if not isinstance(sources, list) or not all(isinstance(source, dict) for source in sources):
            raise AudioHelperError("helper returned an invalid source inventory")
        return tuple(sources)

    async def source_health(self, source_id: UUID) -> Mapping[str, Any]:
        return await self._request(
            {"type": "source.health", "source_id": str(source_id)},
            expected_type="source.health_result",
        )

    async def close(self) -> None:
        async with self._state_lock:
            process = self._process
            if (
                process is not None
                and process.returncode is None
                and self._control_writer is not None
            ):
                with contextlib.suppress(AudioHelperError, TimeoutError):
                    await asyncio.wait_for(
                        self._request_unlocked(
                            {"type": "helper.shutdown"},
                            expected_type="helper.shutdown_ack",
                        ),
                        timeout=HELPER_STOP_TIMEOUT_SECONDS,
                    )
            await self._cleanup_connections()
            if process is not None and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=HELPER_STOP_TIMEOUT_SECONDS)
                except TimeoutError:
                    await self._terminate(process)
            self._process = None
            self._helper_instance_id = None
            self._clock_offset_ns = None
            self._cleanup_socket_directory()

    async def restart(
        self, *, maximum_attempts: int = 3, initial_backoff_seconds: float = 0.05
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must not be negative")
        await self.close()
        last_error: AudioHelperError | None = None
        for attempt in range(maximum_attempts):
            try:
                await self.start()
                return
            except AudioHelperError as exc:
                last_error = exc
                if attempt + 1 < maximum_attempts:
                    await asyncio.sleep(initial_backoff_seconds * (2**attempt))
        raise AudioHelperError("audio helper restart attempts exhausted") from last_error

    async def _request(
        self,
        message: Mapping[str, Any],
        *,
        expected_type: str,
        request_id: str | None = None,
    ) -> Mapping[str, Any]:
        if not self.running:
            raise AudioHelperError("audio helper is not running")
        async with self._control_lock:
            return await asyncio.wait_for(
                self._request_unlocked(
                    message,
                    expected_type=expected_type,
                    request_id=request_id,
                ),
                timeout=HELPER_REQUEST_TIMEOUT_SECONDS,
            )

    async def _request_unlocked(
        self,
        message: Mapping[str, Any],
        *,
        expected_type: str,
        request_id: str | None = None,
    ) -> Mapping[str, Any]:
        if self._control_writer is None:
            raise AudioHelperError("audio helper control connection is unavailable")
        outgoing = dict(message)
        outgoing["protocol_version"] = AUDIO_PROTOCOL_VERSION
        outgoing["request_id"] = request_id or str(uuid4())
        try:
            self._control_writer.write(encode_control_frame(outgoing))
            await self._control_writer.drain()
            response = await self._read_control()
        except (ConnectionError, asyncio.IncompleteReadError, AudioProtocolError) as exc:
            raise AudioHelperError("audio helper control connection failed") from exc
        if response.get("request_id") != outgoing["request_id"]:
            raise AudioHelperError("helper control response request_id mismatch")
        if response.get("type") == "protocol.error":
            code = str(response.get("code", "protocol_error"))
            detail = str(response.get("detail", "helper rejected the command"))
            raise AudioHelperError(f"{code}: {detail}")
        if response.get("type") != expected_type:
            raise AudioHelperError("helper returned an unexpected control response")
        return response

    async def _read_control(self) -> Mapping[str, Any]:
        if self._control_reader is None:
            raise AudioHelperError("audio helper control connection is unavailable")
        header = await self._control_reader.readexactly(CONTROL_HEADER_BYTES)
        payload_bytes = control_payload_bytes_from_header(header)
        payload = await self._control_reader.readexactly(payload_bytes)
        return decode_control_frame(header + payload)

    async def _wait_for_socket(self, control_path: Path) -> None:
        deadline = asyncio.get_running_loop().time() + HELPER_START_TIMEOUT_SECONDS
        while not control_path.exists():
            process = self._process
            if process is None or process.returncode is not None:
                stderr = b"" if process is None else await self._read_stderr(process)
                raise AudioHelperError(self._safe_error("helper failed during startup", stderr))
            if asyncio.get_running_loop().time() >= deadline:
                raise AudioHelperError("helper socket startup timed out")
            await asyncio.sleep(0.01)

    async def _abort_start(self) -> None:
        await self._cleanup_connections()
        process = self._process
        if process is not None and process.returncode is None:
            await self._terminate(process)
        self._process = None
        self._helper_instance_id = None
        self._clock_offset_ns = None
        self._cleanup_socket_directory()

    async def _cleanup_connections(self) -> None:
        for writer_name in ("_control_writer", "_data_writer"):
            writer = getattr(self, writer_name)
            if writer is not None:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()
                setattr(self, writer_name, None)
        self._control_reader = None
        self._data_reader = None

    def _cleanup_socket_directory(self) -> None:
        if self._socket_directory is not None:
            shutil.rmtree(self._socket_directory, ignore_errors=True)
            self._socket_directory = None

    async def _spawn(self, *arguments: str) -> asyncio.subprocess.Process:
        if not self.executable.is_file():
            raise AudioHelperError("audio helper is missing")
        try:
            return await asyncio.create_subprocess_exec(
                str(self.executable),
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise AudioHelperError("audio helper could not be started") from exc

    @staticmethod
    def _validate_descriptor(descriptor: AudioHelperDescriptor) -> None:
        if descriptor.protocol_version != AUDIO_PROTOCOL_VERSION:
            raise AudioHelperError("helper protocol version mismatch")
        if (
            descriptor.canonical_sample_rate != 16_000
            or descriptor.canonical_channels != 1
            or descriptor.canonical_sample_format != "f32le"
        ):
            raise AudioHelperError("helper canonical audio format mismatch")

    @staticmethod
    async def _read_stderr(process: asyncio.subprocess.Process) -> bytes:
        if process.stderr is None:
            return b""
        return await process.stderr.read(MAX_HELPER_DIAGNOSTIC_BYTES + 1)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=HELPER_STOP_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            await process.wait()

    @staticmethod
    def _safe_error(prefix: str, stderr: bytes) -> str:
        if not stderr:
            return prefix
        detail = stderr[:MAX_HELPER_DIAGNOSTIC_BYTES].decode("utf-8", errors="replace").strip()
        return f"{prefix}: {detail[:512]}"
