from pathlib import Path
from types import MappingProxyType

import pytest
from elsewise.evidence.contracts import EvidenceEvent
from elsewise.persistence.database import Database
from elsewise.persistence.models import CaptureSourceRecord, SessionSourceBindingRecord
from elsewise.services.sessions import SessionService
from elsewise.sources.contracts import SourceCategory, SourceDescriptor, SourceRole
from elsewise.sources.manager import SourceManager
from elsewise.speakers.assignments import (
    AssignmentApplyResult,
    SpeakerAssignment,
    SpeakerAssignmentMachine,
)
from elsewise.speech.contracts import AudioRegion, AudioRegionLeaseRegistry
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def test_source_descriptor_supports_capture_and_future_semantic_categories() -> None:
    descriptor = SourceDescriptor(
        id="source-1",
        kind="zoom_plugin",
        category=SourceCategory.SEMANTIC,
        platform="zoom",
        driver_id="zoom_plugin",
        driver_version="1",
        protocol_version=1,
        capabilities=frozenset({"participants", "active_speaker"}),
    )

    assert descriptor.category is SourceCategory.SEMANTIC
    assert "active_speaker" in descriptor.capabilities


def test_normalized_evidence_is_bounded_immutable_and_time_ordered() -> None:
    event = EvidenceEvent(
        event_id="event-1",
        source_id="source-1",
        source_epoch_id="epoch-1",
        capability="active_speaker",
        kind="speaker.started",
        interval_start_us=10,
        interval_end_us=20,
        observed_monotonic_us=30,
        timing_uncertainty_us=5,
        provenance="zoom.plugin",
        confidence=0.9,
        payload={"participant_id": "opaque"},
    )

    assert isinstance(event.payload, MappingProxyType)
    with pytest.raises(TypeError):
        event.payload["participant_id"] = "changed"  # type: ignore[index]
    nested = EvidenceEvent(
        event_id="nested",
        source_id="semantic-1",
        source_epoch_id="epoch-1",
        capability="participants",
        kind="participants.changed",
        interval_start_us=100,
        interval_end_us=100,
        observed_monotonic_us=120,
        timing_uncertainty_us=20,
        provenance="fake.semantic",
        confidence=0.8,
        payload={"participants": [{"id": "opaque-1"}]},
    )
    assert nested.payload["participants"][0]["id"] == "opaque-1"
    with pytest.raises(TypeError):
        nested.payload["participants"][0]["id"] = "changed"
    with pytest.raises(ValueError, match="ordered"):
        EvidenceEvent(
            event_id="event-2",
            source_id="source-1",
            source_epoch_id="epoch-1",
            capability="captions",
            kind="caption.final",
            interval_start_us=20,
            interval_end_us=10,
            observed_monotonic_us=30,
            timing_uncertainty_us=0,
            provenance="meet.dom",
            confidence=1.0,
        )


def test_speaker_assignment_revision_is_independent_from_utterance_text() -> None:
    machine = SpeakerAssignmentMachine()
    anonymous = SpeakerAssignment(
        utterance_id="utterance-1",
        revision=1,
        speaker_role="remote",
        anonymous_track="track-2",
        confidence=1.0,
        provenance="audio.topology",
    )
    alice = SpeakerAssignment(
        utterance_id="utterance-1",
        revision=2,
        speaker_role="remote",
        display_label="Alice",
        profile_id="00000000-0000-0000-0000-000000000001",
        confidence=0.95,
        provenance="speaker.resolver",
        evidence_event_ids=("event-1",),
    )

    assert machine.apply(anonymous) is AssignmentApplyResult.APPLIED
    assert machine.apply(anonymous) is AssignmentApplyResult.DUPLICATE
    assert machine.apply(alice) is AssignmentApplyResult.APPLIED
    assert machine.apply(anonymous) is AssignmentApplyResult.STALE
    assert machine.assignments["utterance-1"].display_label == "Alice"


@pytest.mark.asyncio
async def test_audio_region_registry_holds_no_regions_without_consumers() -> None:
    registry = AudioRegionLeaseRegistry()
    region = AudioRegion(
        source_epoch_id="epoch-1",
        utterance_id="utterance-1",
        role=SourceRole.REMOTE,
        first_sample_position=0,
        last_sample_position=3,
        sample_rate=16_000,
        samples=memoryview(b"\x00\x00\x00\x00"),
    )

    assert await registry.dispatch(region) == ()
    delivered: list[AudioRegion] = []

    async def consume(item: AudioRegion) -> None:
        delivered.append(item)

    registry.register("finalizer", consume)
    assert await registry.dispatch(region) == ("finalizer",)
    registry.unregister("finalizer")
    assert delivered == [region]
    assert await registry.dispatch(region) == ()


def test_native_source_identity_and_active_lane_constraints(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "phase2-contracts.sqlite3")
    database.create_schema()
    session = SessionService(database).create(title="Multi-lane")
    with database.transaction() as db:
        microphone = CaptureSourceRecord(
            source_kind="native_microphone",
            source_category="audio",
            source_role="self",
            target_key="default-input",
            platform="linux",
            driver_id="native_audio",
            driver_version="1",
            protocol_version=1,
            capabilities=["audio_pcm"],
        )
        remote = CaptureSourceRecord(
            source_kind="native_system_audio",
            source_category="audio",
            source_role="remote",
            target_key="default-output",
            platform="linux",
            driver_id="native_audio",
            driver_version="1",
            protocol_version=1,
            capabilities=["audio_pcm"],
        )
        db.add_all((microphone, remote))
        db.flush()
        db.add_all(
            (
                SessionSourceBindingRecord(
                    session_id=session.id,
                    role="self",
                    source_id=microphone.id,
                    requested_mode="auto",
                    effective_mode="native",
                    state="active",
                ),
                SessionSourceBindingRecord(
                    session_id=session.id,
                    role="remote",
                    source_id=remote.id,
                    requested_mode="auto",
                    effective_mode="native",
                    state="active",
                ),
            )
        )

    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(
            SessionSourceBindingRecord(
                session_id=session.id,
                role="self",
                requested_mode="auto",
                effective_mode="unavailable",
                state="waiting",
            )
        )

    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(
            CaptureSourceRecord(
                source_kind="browser_captions",
                source_category="captions",
                source_role="secondary",
                platform="google_meet",
                driver_id="browser_captions",
                driver_version="2",
                protocol_version=2,
                capabilities=["captions"],
            )
        )
    database.dispose()


def test_source_manager_binds_self_and_remote_lanes_independently(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "independent-lanes.sqlite3")
    database.create_schema()
    session = SessionService(database).create(title="Two streams")
    SessionService(database).start(session.id)
    manager = SourceManager(database)
    manager.attach_for_session(session.id)

    self_id, self_epoch = manager.register_local(
        SourceDescriptor(
            id="00000000-0000-4000-8000-000000000011",
            kind="synthetic_audio",
            category=SourceCategory.SYNTHETIC,
            platform="synthetic",
            driver_id="synthetic_audio",
            driver_version="1",
            protocol_version=1,
            capabilities=frozenset({"audio_pcm", "health"}),
        ),
        role=SourceRole.SELF,
        target_key="synthetic-self",
        producer_epoch_id="self-epoch",
    )
    remote_id, remote_epoch = manager.register_local(
        SourceDescriptor(
            id="00000000-0000-4000-8000-000000000012",
            kind="synthetic_audio",
            category=SourceCategory.SYNTHETIC,
            platform="synthetic",
            driver_id="synthetic_audio",
            driver_version="1",
            protocol_version=1,
            capabilities=frozenset({"audio_pcm", "health"}),
        ),
        role=SourceRole.REMOTE,
        target_key="synthetic-remote",
        producer_epoch_id="remote-epoch",
    )

    assert self_epoch is not None and remote_epoch is not None
    with database.transaction() as db:
        bindings = list(
            db.scalars(
                select(SessionSourceBindingRecord).where(
                    SessionSourceBindingRecord.session_id == session.id
                )
            )
        )
        selected = {binding.role: binding.source_id for binding in bindings}
        assert selected["self"] == self_id
        assert selected["remote"] == remote_id
        assert selected["secondary"] is None
    database.dispose()
