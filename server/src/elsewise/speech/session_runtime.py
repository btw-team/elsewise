import asyncio
import contextlib
import os
import platform
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid5

import psutil
from sqlalchemy import select

from elsewise.audio.helper_process import AudioHelperError
from elsewise.audio.multiplexer import AudioStreamHandle
from elsewise.audio.protocol import AUDIO_PROTOCOL_VERSION
from elsewise.audio.runtime import AudioRuntime
from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptureSourceRecord,
    SessionRecord,
    SourceEpochRecord,
)
from elsewise.sources.contracts import SourceCategory, SourceDescriptor, SourceRole
from elsewise.sources.manager import SourceManager
from elsewise.speech.backends.sherpa_worker import SherpaOnnxBackend, SpeechProfileName
from elsewise.speech.contracts import ASRBackend
from elsewise.speech.pipeline import SpeechPipeline
from elsewise.speech.worker_supervisor import SpeechWorkerSupervisor

NATIVE_SOURCE_NAMESPACE = UUID("43254ab7-15fd-45d5-9bf3-42515751a7a5")
NATIVE_SOURCE_KINDS = frozenset(
    {"native_microphone", "native_process_audio", "native_system_audio"}
)
NATIVE_CAPABILITIES = frozenset(
    {"audio_pcm", "device_discovery", "process_targets", "permissions", "health"}
)
NativeSourceKind = Literal["native_microphone", "native_process_audio", "native_system_audio"]
BackendFactory = Callable[[str, str], ASRBackend]


def development_speech_threads() -> int:
    """Keep inference inside the physical CPU budget with interactive headroom."""
    physical_cores = psutil.cpu_count(logical=False)
    available_cores = physical_cores or os.cpu_count() or 1
    reserved_cores = 1 if available_cores > 1 else 0
    return max(1, min(4, available_cores - reserved_cores))


class NativeAudioRuntime(Protocol):
    helper: Any

    async def source_inventory(self) -> tuple[dict[str, Any], ...]: ...

    @property
    def streams(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class DevelopmentSpeechModels:
    whisper_root: Path
    nemotron_root: Path
    parakeet_root: Path
    silero_model: Path

    @classmethod
    def resolve(cls) -> "DevelopmentSpeechModels | None":
        configured = os.environ.get("ELSEWISE_DEVELOPMENT_MODELS")
        root = (
            Path(configured).expanduser()
            if configured
            else Path(__file__).resolve().parents[4] / "models_loaded"
        )
        models = cls(
            whisper_root=root / "sherpa-onnx-whisper-base",
            nemotron_root=(
                root / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11"
            ),
            parakeet_root=root / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
            silero_model=root / "silero" / "silero_vad.onnx",
        )
        required = (
            models.whisper_root / "base-encoder.int8.onnx",
            models.whisper_root / "base-decoder.int8.onnx",
            models.whisper_root / "base-tokens.txt",
            models.silero_model,
        )
        return models if all(path.is_file() for path in required) else None

    def resolve_profile(self, requested: str) -> tuple[SpeechProfileName, Path, Path | None]:
        whisper_available = self._whisper_files(self.whisper_root)
        nemotron_available = self._transducer_files(self.nemotron_root)
        parakeet_available = self._transducer_files(self.parakeet_root)
        maximum = {
            "conservative": 0,
            "standard": 1,
            "best": 2,
            "auto": 2,
        }.get(requested)
        if maximum is None:
            raise RuntimeError(f"unsupported speech profile: {requested}")
        if maximum >= 2 and nemotron_available and parakeet_available:
            return "best", self.nemotron_root, self.parakeet_root
        if maximum >= 1 and nemotron_available:
            return "standard", self.nemotron_root, None
        if whisper_available:
            return "conservative", self.whisper_root, None
        raise RuntimeError("development speech models are missing")

    @staticmethod
    def _whisper_files(root: Path) -> bool:
        return all(
            path.is_file()
            for path in (
                root / "base-encoder.int8.onnx",
                root / "base-decoder.int8.onnx",
                root / "base-tokens.txt",
            )
        )

    @staticmethod
    def _transducer_files(root: Path) -> bool:
        return all(
            path.is_file()
            for path in (
                root / "encoder.int8.onnx",
                root / "decoder.int8.onnx",
                root / "joiner.int8.onnx",
                root / "tokens.txt",
            )
        )


@dataclass(slots=True)
class _NativeLane:
    handle: AudioStreamHandle
    pipeline: SpeechPipeline
    task: asyncio.Task[None]
    monitor_task: asyncio.Task[None] | None = None


class NativeSessionRuntime:
    """Own native Session capture and the per-lane speech pipeline."""

    def __init__(
        self,
        database: Database,
        sources: SourceManager,
        audio: AudioRuntime,
        speech_worker: SpeechWorkerSupervisor,
        *,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.database = database
        self.sources = sources
        self.audio = audio
        self.speech_worker = speech_worker
        self._backend_factory = backend_factory or self._development_backend
        self._lanes: dict[str, _NativeLane] = {}
        self._lock = asyncio.Lock()

    async def prepare_session(self, session_id: str) -> dict[SourceRole, str]:
        """Discover and register the concrete native sources selected for a Session."""
        with self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            if session is None:
                return {}
            self_enabled = session.self_audio_enabled
            remote_enabled = session.remote_audio_enabled
            remote_target_key = session.remote_target_key or None
        if not (self_enabled or remote_enabled):
            return {}
        try:
            inventory = await self.audio.source_inventory()
        except (AudioHelperError, OSError) as error:
            log_event("native_audio.discovery_failed", error_code=type(error).__name__)
            return {}
        inventory = tuple(source for source in inventory if self._valid_candidate(source))

        selected: dict[SourceRole, Mapping[str, Any]] = {}
        if self_enabled:
            microphone = self._choose(inventory, "native_microphone")
            if microphone is not None:
                selected[SourceRole.SELF] = microphone
        if remote_enabled:
            remote: Mapping[str, Any] | None = None
            if remote_target_key:
                remote = next(
                    (
                        source
                        for source in inventory
                        if source.get("source_kind")
                        in {"native_process_audio", "native_system_audio"}
                        and source.get("target_key") == remote_target_key
                        and source.get("available") is True
                    ),
                    None,
                )
            if remote is None:
                remote = self._choose(inventory, "native_system_audio")
            if remote is not None:
                selected[SourceRole.REMOTE] = remote

        producer_epoch_id = str(self.audio.helper.helper_instance_id or "helper-starting")
        registered: dict[SourceRole, str] = {}
        for role, source in selected.items():
            kind = str(source["source_kind"])
            follow_default = source.get("is_default") is True and (
                role is SourceRole.SELF or (role is SourceRole.REMOTE and remote_target_key is None)
            )
            target_key = "default" if follow_default else str(source["target_key"])
            source_id = str(uuid5(NATIVE_SOURCE_NAMESPACE, f"{kind}\0{target_key}"))
            descriptor = SourceDescriptor(
                id=source_id,
                kind=kind,
                category=SourceCategory.AUDIO,
                platform=platform.system().lower(),
                driver_id="native_audio",
                driver_version="1",
                protocol_version=AUDIO_PROTOCOL_VERSION,
                capabilities=NATIVE_CAPABILITIES,
            )
            self.sources.register_local(
                descriptor,
                role=role,
                target_key=target_key,
                producer_epoch_id=producer_epoch_id,
                sanitized_metadata={
                    "display_name": str(source.get("display_name", "Native audio"))[:256],
                    "is_default": bool(source.get("is_default", False)),
                    "active": bool(source.get("active", False)),
                },
            )
            registered[role] = source_id
        return registered

    def handles_epoch(self, epoch_id: str) -> bool:
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            source = db.get(CaptureSourceRecord, epoch.source_id) if epoch is not None else None
            return source is not None and source.driver_id == "native_audio"

    async def start_epoch(self, epoch_id: str) -> str:
        async with self._lock:
            if epoch_id in self._lanes:
                return "started"
            details = self._epoch_details(epoch_id)
            if details is None:
                return "source_not_bound"
            source_id, source_kind, target_key, language, requested_profile = details
            pipeline: SpeechPipeline | None = None
            try:
                pipeline = SpeechPipeline(
                    self.database,
                    epoch_id=epoch_id,
                    backend=self._backend_factory(language, requested_profile),
                    language=self._worker_language(language),
                )
                await pipeline.start()
                handle = await self.audio.streams.start_native(
                    source_kind=source_kind,
                    source_id=UUID(source_id),
                    epoch_id=UUID(epoch_id),
                    target_key=target_key,
                )
            except Exception as error:
                error_code = self._error_code(error)
                log_event(
                    "native_speech.start_failed",
                    reason=error_code,
                    error_type=type(error).__name__,
                )
                if pipeline is not None:
                    with contextlib.suppress(Exception):
                        await pipeline.stop(timeout_seconds=1.0)
                self._mark_failed(epoch_id, error_code)
                return "failed"
            task = asyncio.create_task(
                self._consume(epoch_id, handle, pipeline),
                name=f"elsewise-native-speech-{epoch_id}",
            )
            lane = _NativeLane(handle=handle, pipeline=pipeline, task=task)
            self._lanes[epoch_id] = lane
            lane.monitor_task = asyncio.create_task(
                self._monitor(epoch_id, handle.source_id, task),
                name=f"elsewise-native-health-{epoch_id}",
            )
            self._mark_started(epoch_id, pipeline.backend)
            return "started"

    async def finalize_epoch(self, epoch_id: str, *, timeout_seconds: float) -> bool:
        async with self._lock:
            lane = self._lanes.get(epoch_id)
        if lane is None:
            return self.handles_epoch(epoch_id)
        deadline = monotonic() + timeout_seconds
        try:
            await asyncio.wait_for(lane.handle.stop(), timeout=max(0.01, timeout_seconds))
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            await asyncio.wait_for(asyncio.shield(lane.task), timeout=remaining)
        except (AudioHelperError, TimeoutError):
            lane.task.cancel()
            await asyncio.gather(lane.task, return_exceptions=True)
            self._mark_degraded(epoch_id, "finalize_timeout")
        finally:
            if lane.monitor_task is not None:
                lane.monitor_task.cancel()
                await asyncio.gather(lane.monitor_task, return_exceptions=True)
            async with self._lock:
                self._lanes.pop(epoch_id, None)
        return True

    async def finalize_session(self, session_id: str, *, hard_budget_seconds: float) -> None:
        with self.database.transaction() as db:
            epoch_ids = list(
                db.scalars(
                    select(SourceEpochRecord.id).where(
                        SourceEpochRecord.session_id == session_id,
                        SourceEpochRecord.state.in_(("starting", "running", "stopping")),
                    )
                )
            )
        native_ids = [epoch_id for epoch_id in epoch_ids if self.handles_epoch(epoch_id)]
        if not native_ids:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(
                    *(
                        self.finalize_epoch(epoch_id, timeout_seconds=hard_budget_seconds)
                        for epoch_id in native_ids
                    ),
                    return_exceptions=True,
                ),
                timeout=hard_budget_seconds + 0.1,
            )

    async def close(self) -> None:
        async with self._lock:
            epoch_ids = tuple(self._lanes)
        if epoch_ids:
            await asyncio.gather(
                *(self.finalize_epoch(epoch_id, timeout_seconds=1.0) for epoch_id in epoch_ids),
                return_exceptions=True,
            )
        await self.speech_worker.close()

    async def _consume(
        self, epoch_id: str, handle: AudioStreamHandle, pipeline: SpeechPipeline
    ) -> None:
        failure: BaseException | None = None
        try:
            async for frame in handle.frames():
                pipeline.push(frame)
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            failure = error
            error_code = self._error_code(error)
            log_event(
                "native_speech.consume_failed",
                reason=error_code,
                error_type=type(error).__name__,
            )
            self._mark_degraded(epoch_id, error_code)
            with contextlib.suppress(AudioHelperError):
                await handle.stop()
        finally:
            try:
                await pipeline.stop(timeout_seconds=2.0)
            except BaseException as error:
                if failure is None:
                    self._mark_degraded(epoch_id, self._error_code(error))

    async def _monitor(
        self, epoch_id: str, source_id: UUID, consume_task: asyncio.Task[None]
    ) -> None:
        while not consume_task.done():
            await asyncio.sleep(1.0)
            try:
                payload = await self.audio.helper.source_health(source_id)
                metrics = {
                    key: int(payload.get(key, 0))
                    for key in (
                        "backpressure_count",
                        "dropped_callback_blocks",
                        "xruns",
                        "route_changes",
                        "capture_errors",
                    )
                }
            except (AudioHelperError, OSError, TypeError, ValueError):
                self._mark_degraded(epoch_id, "helper_crashed")
                return
            self.sources.update_local_epoch_metrics(epoch_id, metrics)

    def _epoch_details(self, epoch_id: str) -> tuple[str, NativeSourceKind, str, str, str] | None:
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            source = db.get(CaptureSourceRecord, epoch.source_id) if epoch is not None else None
            session = db.get(SessionRecord, epoch.session_id) if epoch is not None else None
            if (
                epoch is None
                or source is None
                or session is None
                or source.driver_id != "native_audio"
                or source.source_kind not in NATIVE_SOURCE_KINDS
                or source.target_key is None
            ):
                return None
            return (
                source.id,
                cast(NativeSourceKind, source.source_kind),
                source.target_key,
                session.language,
                session.requested_speech_profile,
            )

    def _development_backend(self, _: str, requested_profile: str) -> ASRBackend:
        models = DevelopmentSpeechModels.resolve()
        if models is None:
            raise RuntimeError("development speech models are missing")
        effective_profile, model_root, finalizer_root = models.resolve_profile(requested_profile)
        return SherpaOnnxBackend(
            supervisor=self.speech_worker,
            profile=effective_profile,
            model_root=model_root,
            silero_model=models.silero_model,
            finalizer_root=finalizer_root,
            threads=development_speech_threads(),
        )

    def _mark_started(self, epoch_id: str, backend: ASRBackend) -> None:
        self.sources.mark_local_epoch_started(
            epoch_id,
            helper_instance_id=str(self.audio.helper.helper_instance_id or "") or None,
            helper_protocol_version=AUDIO_PROTOCOL_VERSION,
            effective_format={
                "sample_rate": 16_000,
                "channels": 1,
                "format": "f32le",
            },
            effective_backend=f"{backend.id}:{backend.model_id}",
        )

    def _mark_failed(self, epoch_id: str, error_code: str) -> None:
        self.sources.mark_local_epoch_degraded(epoch_id, error_code=error_code, terminal=True)

    def _mark_degraded(self, epoch_id: str, error_code: str) -> None:
        self.sources.mark_local_epoch_degraded(epoch_id, error_code=error_code, terminal=False)

    @staticmethod
    def _choose(
        inventory: tuple[dict[str, Any], ...], source_kind: NativeSourceKind
    ) -> Mapping[str, Any] | None:
        candidates = [
            source
            for source in inventory
            if source.get("source_kind") == source_kind and source.get("available") is True
        ]
        default = next((source for source in candidates if source.get("is_default") is True), None)
        return default or (candidates[0] if candidates else None)

    @staticmethod
    def _valid_candidate(source: Mapping[str, Any]) -> bool:
        kind = source.get("source_kind")
        target_key = source.get("target_key")
        display_name = source.get("display_name")
        return (
            isinstance(kind, str)
            and kind in NATIVE_SOURCE_KINDS
            and isinstance(target_key, str)
            and 0 < len(target_key) <= 256
            and isinstance(display_name, str)
            and 0 < len(display_name) <= 512
            and isinstance(source.get("available"), bool)
            and isinstance(source.get("is_default"), bool)
        )

    @staticmethod
    def _worker_language(language: str) -> str:
        return "pt" if language.lower() == "pt-br" else language.lower()

    @staticmethod
    def _error_code(error: BaseException) -> str:
        message = str(error).lower()
        if "model" in message and ("missing" in message or "required" in message):
            return "model_missing"
        if "permission" in message:
            return "permission_denied"
        if any(
            marker in message
            for marker in ("pipewire", "pulseaudio", "linux audio recorder", "system-audio")
        ):
            return "loopback_unavailable"
        if "queue" in message or "backpressure" in message:
            return "asr_overloaded"
        if isinstance(error, AudioHelperError):
            return "helper_crashed"
        return "asr_failed"
