import struct
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from elsewise.audio.protocol import AudioFrame, AudioFrameFlags
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptureSourceRecord,
    RecordingSegmentRecord,
    SessionSourceBindingRecord,
    SourceEpochRecord,
    UiEventRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
)
from elsewise.services.sessions import SessionService
from elsewise.speech.backends.fake import FakeASRBackend
from elsewise.speech.contracts import AudioRegion, AudioRegionLeaseRegistry, SpeechEvent
from elsewise.speech.pipeline import SpeechPipeline
from sqlalchemy import select

SOURCE_ID = UUID("00000000-0000-4000-8000-000000000021")
EPOCH_ID = UUID("00000000-0000-4000-8000-000000000022")


def frame(sequence: int, *, flags: AudioFrameFlags = AudioFrameFlags.NONE) -> AudioFrame:
    return AudioFrame(
        source_id=SOURCE_ID,
        epoch_id=EPOCH_ID,
        sequence=sequence,
        source_sample_position=sequence * 320,
        host_monotonic_ns=sequence * 20_000_000,
        frame_samples=320,
        flags=flags,
        pcm=struct.pack("<320f", *([0.1] * 320)),
    )


def audio_epoch(database: Database) -> str:
    session = SessionService(database).create(title="Speech")
    SessionService(database).start(session.id)
    with database.transaction() as db:
        segment = db.scalar(
            select(RecordingSegmentRecord).where(RecordingSegmentRecord.session_id == session.id)
        )
        assert segment is not None
        source = CaptureSourceRecord(
            id=str(SOURCE_ID),
            source_kind="synthetic_audio",
            source_category="synthetic",
            source_role="self",
            target_key="fixture",
            platform="synthetic",
            driver_id="synthetic_audio",
            driver_version="1",
            protocol_version=1,
            capabilities=["audio_pcm", "health"],
        )
        db.add(source)
        binding = SessionSourceBindingRecord(
            session_id=session.id,
            segment_id=segment.id,
            role="self",
            source_id=source.id,
            requested_mode="auto",
            effective_mode="synthetic",
            state="active",
        )
        db.add(binding)
        db.flush()
        epoch = SourceEpochRecord(
            id=str(EPOCH_ID),
            source_id=source.id,
            binding_id=binding.id,
            session_id=session.id,
            segment_id=segment.id,
            producer_epoch_id="synthetic-1",
            helper_instance_id="helper-1",
            helper_protocol_version=1,
            effective_format={"sample_rate": 16_000, "channels": 1, "format": "f32le"},
            effective_backend="fake",
            state="running",
        )
        db.add(epoch)
        return epoch.id


@pytest.mark.asyncio
async def test_speech_pipeline_projects_audio_revisions_and_topology_assignment(
    tmp_path: Path,
) -> None:
    database = Database.from_path(tmp_path / "speech.sqlite3")
    database.create_schema()
    epoch_id = audio_epoch(database)
    backend = FakeASRBackend(
        events_by_sequence={
            0: (
                SpeechEvent(
                    utterance_id="speech-1",
                    revision=1,
                    kind="partial",
                    text="hel",
                    first_sample_position=0,
                    last_sample_position=320,
                    confidence=0.7,
                ),
            ),
            1: (
                SpeechEvent(
                    utterance_id="speech-1",
                    revision=2,
                    kind="final",
                    text="hello",
                    first_sample_position=0,
                    last_sample_position=640,
                    confidence=0.9,
                    durable=True,
                ),
            ),
        }
    )
    pipeline = SpeechPipeline(
        database,
        epoch_id=epoch_id,
        backend=backend,
        language="en",
    )
    await pipeline.start()
    pipeline.push(frame(0, flags=AudioFrameFlags.DISCONTINUITY))
    pipeline.push(frame(1))
    await pipeline.stop(timeout_seconds=1.0)

    with database.transaction() as db:
        utterance = db.scalar(select(UtteranceRecord))
        assert utterance is not None
        assert utterance.text == "hello"
        assert utterance.revision == 2
        assert utterance.finalization_state == "durable_final"
        assert utterance.first_client_seq is None
        assert utterance.last_audio_sample_position == 640
        assignment = db.scalar(select(UtteranceSpeakerAssignmentRecord))
        assert assignment is not None
        assert assignment.speaker_role == "self"
        assert assignment.revision == 1
        epoch = db.get(SourceEpochRecord, epoch_id)
        assert epoch is not None
        assert epoch.first_sequence == 0 and epoch.last_sequence == 1
        assert epoch.discontinuity_count == 1
        events = list(
            db.scalars(
                select(UiEventRecord)
                .where(UiEventRecord.event_type.like("utterance.%"))
                .order_by(UiEventRecord.id)
            )
        )
        assert len(events) == 2
        payload = dict(events[-1].payload)
        first_received_at = payload.pop("first_received_at")
        last_received_at = payload.pop("last_received_at")
        assert isinstance(first_received_at, str)
        assert isinstance(last_received_at, str)
        datetime.fromisoformat(first_received_at)
        datetime.fromisoformat(last_received_at)
        assert payload == {
            "id": utterance.id,
            "session_id": utterance.session_id,
            "segment_id": utterance.segment_id,
            "source_epoch_id": utterance.source_epoch_id,
            "utterance_id": "speech-1",
            "revision": 2,
            "speaker": "You",
            "speaker_role": "self",
            "text": "hello",
            "final": True,
            "first_session_offset_us": 0,
            "last_session_offset_us": 40_000,
            "first_client_seq": None,
            "last_client_seq": None,
            "first_audio_sample_position": 0,
            "last_audio_sample_position": 640,
            "finalization_state": "durable_final",
            "asr_backend": "fake",
            "asr_model_id": "fake-deterministic",
            "asr_model_version": "1",
            "transcript_confidence": 0.9,
        }
    database.dispose()


@pytest.mark.asyncio
async def test_speech_pipeline_dispatches_bounded_final_audio_region(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "speech-region.sqlite3")
    database.create_schema()
    epoch_id = audio_epoch(database)
    consumers = AudioRegionLeaseRegistry()
    delivered: list[AudioRegion] = []

    async def consume(region: AudioRegion) -> None:
        delivered.append(region)

    consumers.register("finalizer", consume)
    backend = FakeASRBackend(
        flush_events=(
            SpeechEvent(
                utterance_id="speech-region",
                revision=1,
                kind="final",
                text="speech",
                first_sample_position=0,
                last_sample_position=640,
                durable=False,
            ),
        )
    )
    pipeline = SpeechPipeline(
        database,
        epoch_id=epoch_id,
        backend=backend,
        language="en",
        region_consumers=consumers,
    )
    await pipeline.start()
    pipeline.push(frame(0))
    pipeline.push(frame(1))
    await pipeline.stop(timeout_seconds=1.0)

    assert len(delivered) == 1
    assert delivered[0].role.value == "self"
    assert len(delivered[0].samples) == 640 * 4
    assert pipeline.rolling_buffer.size_bytes == 0
    database.dispose()


@pytest.mark.asyncio
async def test_speech_pipeline_rejects_unmarked_continuity_gap(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "speech-gap.sqlite3")
    database.create_schema()
    pipeline = SpeechPipeline(
        database,
        epoch_id=audio_epoch(database),
        backend=FakeASRBackend(),
        language="en",
    )
    await pipeline.start()
    pipeline.push(frame(0))
    with pytest.raises(RuntimeError, match="continuity"):
        pipeline.push(frame(2))
    with pytest.raises(RuntimeError, match="speech worker failed"):
        await pipeline.stop(timeout_seconds=1.0)
    database.dispose()


@pytest.mark.asyncio
async def test_durable_speech_text_rejects_late_correction(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "durable.sqlite3")
    database.create_schema()
    epoch_id = audio_epoch(database)
    backend = FakeASRBackend(
        flush_events=(
            SpeechEvent(
                utterance_id="speech-1",
                revision=1,
                kind="final",
                text="final",
                first_sample_position=0,
                last_sample_position=320,
                durable=True,
            ),
        )
    )
    pipeline = SpeechPipeline(
        database,
        epoch_id=epoch_id,
        backend=backend,
        language="en",
    )
    await pipeline.start()
    await pipeline.stop(timeout_seconds=1.0)

    result = pipeline.projector.process(
        epoch_id,
        SpeechEvent(
            utterance_id="speech-1",
            revision=2,
            kind="final",
            text="late correction",
            first_sample_position=0,
            last_sample_position=320,
            durable=True,
        ),
        backend,
    )
    assert result == "final_utterance_immutable"
    database.dispose()
