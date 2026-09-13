import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from elsewise.audio.protocol import (
    AUDIO_HEADER_BYTES,
    AUDIO_PROTOCOL_VERSION,
    AudioFrame,
    AudioProtocolError,
    audio_payload_bytes_from_header,
    decode_audio_frame,
)

HELPER_PROBE_TIMEOUT_SECONDS = 5.0
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
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

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
        if descriptor.protocol_version != AUDIO_PROTOCOL_VERSION:
            raise AudioHelperError("helper protocol version mismatch")
        if (
            descriptor.canonical_sample_rate != 16_000
            or descriptor.canonical_channels != 1
            or descriptor.canonical_sample_format != "f32le"
        ):
            raise AudioHelperError("helper canonical audio format mismatch")
        return descriptor

    async def synthetic_frames(
        self,
        *,
        source_id: UUID,
        epoch_id: UUID,
        frame_count: int,
    ) -> AsyncIterator[AudioFrame]:
        if not 1 <= frame_count <= 100_000:
            raise ValueError("frame_count must be between 1 and 100000")
        async with self._lock:
            if self.running:
                raise AudioHelperError("helper is already running")
            process = await self._spawn(
                "--synthetic",
                "--source-id",
                str(source_id),
                "--epoch-id",
                str(epoch_id),
                "--frames",
                str(frame_count),
            )
            self._process = process
            assert process.stdout is not None
            try:
                for _ in range(frame_count):
                    try:
                        header = await process.stdout.readexactly(AUDIO_HEADER_BYTES)
                        payload_bytes = audio_payload_bytes_from_header(header)
                        payload = await process.stdout.readexactly(payload_bytes)
                    except asyncio.IncompleteReadError as exc:
                        raise AudioHelperError("helper returned a truncated audio stream") from exc
                    try:
                        frame = decode_audio_frame(header + payload)
                    except AudioProtocolError as exc:
                        raise AudioHelperError(str(exc)) from exc
                    if frame.source_id != source_id or frame.epoch_id != epoch_id:
                        raise AudioHelperError("helper returned a frame for another stream")
                    yield frame
                return_code = await process.wait()
                if return_code != 0:
                    stderr = await self._read_stderr(process)
                    raise AudioHelperError(self._safe_error("helper failed", stderr))
            finally:
                if process.returncode is None:
                    await self._terminate(process)
                self._process = None

    async def close(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            await self._terminate(process)
        self._process = None

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
    async def _read_stderr(process: asyncio.subprocess.Process) -> bytes:
        if process.stderr is None:
            return b""
        return await process.stderr.read(MAX_HELPER_DIAGNOSTIC_BYTES + 1)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        process.terminate()
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
