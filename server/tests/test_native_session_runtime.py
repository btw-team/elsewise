import asyncio
import struct
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from elsewise.audio.protocol import AudioFrame, AudioFrameFlags
from elsewise.persistence.database import Database
from elsewise.persistence.models import SourceEpochRecord, UtteranceRecord
from elsewise.services.session_controller import SessionController
from elsewise.services.sessions import SessionService
from elsewise.services.transitions import TransitionExecutor
from elsewise.sources.manager import SourceManager
from elsewise.speech.backends.fake import FakeASRBackend
from elsewise.speech.contracts import SpeechEvent
from elsewise.speech.session_runtime import DevelopmentSpeechModels, NativeSessionRuntime
from sqlalchemy import select


class FakeHelper:
    helper_instance_id = UUID("00000000-0000-4000-8000-000000000099")

    async def source_health(self, _: UUID) -> dict[str, int]:
        return {}


class FakeHandle:
    def __init__(self, source_id: UUID, epoch_id: UUID) -> None:
        self.source_id = source_id
        self.epoch_id = epoch_id
        self._queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue()

    async def frames(self):  # type: ignore[no-untyped-def]
        while True:
            frame = await self._queue.get()
            if frame is None:
                return
            yield frame

    async def stop(self) -> None:
        await self._queue.put(
            AudioFrame(
                source_id=self.source_id,
                epoch_id=self.epoch_id,
                sequence=0,
                source_sample_position=0,
                host_monotonic_ns=0,
                frame_samples=320,
                flags=AudioFrameFlags.END_OF_STREAM,
                pcm=struct.pack("<320f", *([0.1] * 320)),
            )
        )
        await self._queue.put(None)


class FakeMultiplexer:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []

    async def start_native(
        self,
        *,
        source_kind: str,
        source_id: UUID,
        epoch_id: UUID,
        target_key: str,
    ) -> FakeHandle:
        self.started.append((source_kind, target_key))
        return FakeHandle(source_id, epoch_id)


class FakeAudioRuntime:
    def __init__(self) -> None:
        self.helper = FakeHelper()
        self.streams = FakeMultiplexer()

    async def source_inventory(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "source_kind": "native_microphone",
                "target_key": "mic:default",
                "display_name": "Test microphone",
                "available": True,
                "is_default": True,
                "active": True,
            },
            {
                "source_kind": "native_system_audio",
                "target_key": "output:default",
                "display_name": "Test output",
                "available": True,
                "is_default": True,
                "active": True,
            },
        )


class FakeSpeechWorker:
    async def close(self) -> None:
        return None


def make_development_models(tmp_path: Path) -> DevelopmentSpeechModels:
    whisper_root = tmp_path / "whisper"
    nemotron_root = tmp_path / "nemotron"
    parakeet_root = tmp_path / "parakeet"
    silero_model = tmp_path / "silero" / "silero_vad.onnx"
    for path in (
        whisper_root / "base-encoder.int8.onnx",
        whisper_root / "base-decoder.int8.onnx",
        whisper_root / "base-tokens.txt",
        nemotron_root / "encoder.int8.onnx",
        nemotron_root / "decoder.int8.onnx",
        nemotron_root / "joiner.int8.onnx",
        nemotron_root / "tokens.txt",
        parakeet_root / "encoder.int8.onnx",
        parakeet_root / "decoder.int8.onnx",
        parakeet_root / "joiner.int8.onnx",
        parakeet_root / "tokens.txt",
        silero_model,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return DevelopmentSpeechModels(
        whisper_root=whisper_root,
        nemotron_root=nemotron_root,
        parakeet_root=parakeet_root,
        silero_model=silero_model,
    )


def test_development_models_resolve_real_profile_matrix(tmp_path: Path) -> None:
    models = make_development_models(tmp_path)

    assert models.resolve_profile("conservative") == (
        "conservative",
        models.whisper_root,
        None,
    )
    assert models.resolve_profile("standard") == ("standard", models.nemotron_root, None)
    assert models.resolve_profile("best") == (
        "best",
        models.nemotron_root,
        models.parakeet_root,
    )
    assert models.resolve_profile("auto") == (
        "best",
        models.nemotron_root,
        models.parakeet_root,
    )


def test_development_models_downgrade_to_highest_available_profile(tmp_path: Path) -> None:
    models = make_development_models(tmp_path)
    (models.parakeet_root / "encoder.int8.onnx").unlink()
    assert models.resolve_profile("best") == ("standard", models.nemotron_root, None)

    (models.nemotron_root / "encoder.int8.onnx").unlink()
    assert models.resolve_profile("best") == (
        "conservative",
        models.whisper_root,
        None,
    )
    assert models.resolve_profile("standard") == (
        "conservative",
        models.whisper_root,
        None,
    )


def backend(_: str, __: str) -> FakeASRBackend:
    return FakeASRBackend(
        flush_events=(
            SpeechEvent(
                utterance_id="native-final",
                revision=1,
                kind="final",
                text="captured speech",
                first_sample_position=0,
                last_sample_position=320,
                durable=True,
            ),
        )
    )


@pytest.mark.asyncio
async def test_session_start_runs_two_native_lanes_and_stop_flushes_speech(
    tmp_path: Path,
) -> None:
    database = Database.from_path(tmp_path / "native-session.sqlite3")
    database.create_schema()
    sources = SourceManager(database)
    audio = FakeAudioRuntime()
    runtime = NativeSessionRuntime(
        database,
        sources,
        audio,  # type: ignore[arg-type]
        FakeSpeechWorker(),  # type: ignore[arg-type]
        backend_factory=backend,
    )
    controller = SessionController(database, sources, TransitionExecutor(), runtime)
    session = SessionService(database).create(
        title="Native session",
        language="en",
        secondary_fallback_enabled=False,
    )

    started = await controller.start(session.id)
    assert started.recording_status == "running"
    for _ in range(20):
        if len(audio.streams.started) == 2:
            break
        await asyncio.sleep(0)
    assert sorted(audio.streams.started) == [
        ("native_microphone", "default"),
        ("native_system_audio", "default"),
    ]

    stopped = await controller.stop(session.id)
    assert stopped.recording_status == "stopped"
    with database.transaction() as db:
        epochs = list(db.scalars(select(SourceEpochRecord)))
        assert len(epochs) == 2
        assert all(epoch.state == "stopped" for epoch in epochs)
        utterances = list(db.scalars(select(UtteranceRecord)))
        assert len(utterances) == 2
        assert {utterance.text for utterance in utterances} == {"captured speech"}
    await controller.close()
    database.dispose()


@pytest.mark.asyncio
async def test_missing_speech_backend_degrades_lane_without_stopping_session(
    tmp_path: Path,
) -> None:
    database = Database.from_path(tmp_path / "native-missing-model.sqlite3")
    database.create_schema()
    sources = SourceManager(database)
    audio = FakeAudioRuntime()

    def missing_backend(_: str, __: str) -> FakeASRBackend:
        raise RuntimeError("development speech models are missing")

    runtime = NativeSessionRuntime(
        database,
        sources,
        audio,  # type: ignore[arg-type]
        FakeSpeechWorker(),  # type: ignore[arg-type]
        backend_factory=missing_backend,
    )
    controller = SessionController(database, sources, TransitionExecutor(), runtime)
    session = SessionService(database).create(
        title="Missing model",
        remote_audio_enabled=False,
        secondary_fallback_enabled=False,
    )

    await controller.start(session.id)
    for _ in range(20):
        if SessionService(database).get(session.id).source_status == "degraded":
            break
        await asyncio.sleep(0)
    current = SessionService(database).get(session.id)
    assert current.recording_status == "running"
    assert current.source_status == "degraded"
    with database.transaction() as db:
        epoch = db.scalar(select(SourceEpochRecord))
        assert epoch is not None
        assert epoch.state == "failed"
        assert epoch.last_error_code == "model_missing"
    await controller.stop(session.id)
    await controller.close()
    database.dispose()
