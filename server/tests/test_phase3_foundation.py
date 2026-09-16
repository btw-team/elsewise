from pathlib import Path
from uuid import uuid4

from elsewise.evidence import ActiveSpeakerIndex, EvidenceBus, EvidenceEvent, PublishResult
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    ActivityParticipantRecord,
    ActivityRecord,
    CaptureSourceRecord,
    PairedClientRecord,
    RecordingSegmentRecord,
    SessionRecord,
    SessionSourceBindingRecord,
    SourceEpochRecord,
    SpeakerProfileAliasRecord,
    SpeakerPrototypeRecord,
    SpeakerSemanticIdentityRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
)
from elsewise.protocol.models import EvidenceEmit
from elsewise.sources.projectors.evidence import EvidenceProjector
from elsewise.speakers.registry import SpeakerRegistry
from elsewise.speakers.service import assign_speaker_manually
from sqlalchemy import inspect, select


def _event(event_id: str) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        source_id="source",
        source_epoch_id="epoch",
        capability="active_speaker",
        kind="speaker.started",
        interval_start_us=0,
        interval_end_us=1,
        observed_monotonic_us=1,
        timing_uncertainty_us=0,
        provenance="test.fixture",
        confidence=1.0,
        payload={"participant_id": "person"},
    )


def test_evidence_bus_is_bounded_deduplicated_and_consumer_isolated() -> None:
    bus = EvidenceBus(max_events=2, dedupe_size=2)
    delivered: list[str] = []
    bus.subscribe("broken", lambda _event: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe("healthy", lambda event: delivered.append(event.event_id))

    assert bus.publish(_event("one")) is PublishResult.REJECTED
    assert bus.publish(_event("one")) is PublishResult.DUPLICATE
    assert bus.publish(_event("two")) is PublishResult.REJECTED
    assert bus.publish(_event("three")) is PublishResult.REJECTED

    assert delivered == ["one", "two", "three"]
    assert [item.event_id for item in bus.events()] == ["two", "three"]
    assert bus.snapshot().queued == 2
    assert bus.snapshot().evicted == 1


def test_active_speaker_index_joins_intervals_and_filters_overlap() -> None:
    index = ActiveSpeakerIndex(max_intervals=2, max_open=2)
    started = _event("started")
    stopped = EvidenceEvent(
        event_id="stopped",
        source_id=started.source_id,
        source_epoch_id=started.source_epoch_id,
        capability="active_speaker",
        kind="speaker.stopped",
        interval_start_us=5,
        interval_end_us=10,
        observed_monotonic_us=10,
        timing_uncertainty_us=0,
        provenance=started.provenance,
        confidence=0.8,
        payload={"participant_id": "person"},
    )
    index.consume(started)
    index.consume(stopped)

    assert index.intervals(start_us=2, end_us=8) == (
        index.intervals()[0],
    )
    assert index.intervals()[0].confidence == 0.8
    assert index.intervals(start_us=11) == ()


def _semantic_database(path: Path) -> tuple[Database, str, str, str, str]:
    database = Database.from_path(path)
    database.create_schema()
    with database.transaction() as db:
        session = SessionRecord(
            title="Semantic session",
            recording_status="running",
            monotonic_origin_ns=1_000_000_000,
        )
        db.add(session)
        db.flush()
        segment = RecordingSegmentRecord(session_id=session.id, sequence=1)
        client = PairedClientRecord(
            installation_id=str(uuid4()),
            browser_family="chrome",
            display_name="Test browser",
            credential_digest="0" * 64,
        )
        db.add_all([segment, client])
        db.flush()
        source = CaptureSourceRecord(
            paired_client_id=client.id,
            platform="synthetic",
            tab_instance_id="tab-1",
            activity_key="meeting-1",
            capabilities=[
                "activity_lifecycle",
                "participants",
                "self_identity",
                "active_speaker",
                "captions",
                "mute_state",
                "hand_raise",
                "presentation",
                "recording_state",
            ],
        )
        db.add(source)
        db.flush()
        binding = SessionSourceBindingRecord(
            session_id=session.id,
            segment_id=segment.id,
            role="secondary",
            source_id=source.id,
            requested_mode="explicit",
            effective_mode="captions",
            state="active",
        )
        db.add(binding)
        db.flush()
        epoch = SourceEpochRecord(
            source_id=source.id,
            binding_id=binding.id,
            session_id=session.id,
            segment_id=segment.id,
            producer_epoch_id="producer-1",
        )
        db.add(epoch)
        db.flush()
        return database, session.id, segment.id, source.id, epoch.id


def _emit(
    source_id: str,
    epoch_id: str,
    capability: str,
    kind: str,
    payload: dict[str, object],
    *,
    sequence: int,
) -> EvidenceEmit:
    return EvidenceEmit.model_validate(
        {
            "type": "evidence.emit",
            "protocol_version": 3,
            "event_id": str(uuid4()),
            "source_id": source_id,
            "source_epoch_id": epoch_id,
            "client_seq": sequence,
            "capability": capability,
            "kind": kind,
            "interval_start_us": sequence * 1_000,
            "interval_end_us": sequence * 1_000,
            "source_time_us": sequence * 1_000,
            "provenance": "synthetic.fixture",
            "confidence": 0.9,
            "payload": payload,
        }
    )


def test_semantic_projector_materializes_current_state_without_event_journal(
    tmp_path: Path,
) -> None:
    database, session_id, _segment_id, source_id, epoch_id = _semantic_database(
        tmp_path / "semantic.sqlite3"
    )
    projector = EvidenceProjector(database, monotonic_us=lambda: 1_001_000)
    messages: list[tuple[str, str, dict[str, object]]] = [
        ("activity_lifecycle", "activity.started", {}),
        (
            "participants",
            "participant.upsert",
            {"participant_id": "p-1", "display_label": "Alice"},
        ),
        ("self_identity", "participant.self", {"participant_id": "p-1"}),
        ("mute_state", "participant.muted", {"participant_id": "p-1"}),
        ("hand_raise", "participant.hand_raised", {"participant_id": "p-1"}),
        ("presentation", "presentation.started", {}),
        ("recording_state", "recording.started", {}),
    ]
    for sequence, (capability, kind, payload) in enumerate(messages, start=1):
        assert (
            projector.process(
                _emit(
                    source_id,
                    epoch_id,
                    capability,
                    kind,
                    payload,
                    sequence=sequence,
                )
            )
            == "applied"
        )

    with database.transaction() as db:
        activity = db.scalar(
            select(ActivityRecord).where(ActivityRecord.session_id == session_id)
        )
        assert activity is not None
        assert activity.state == "running"
        assert activity.presentation_state == "active"
        assert activity.recording_state == "active"
        participant = db.scalar(select(ActivityParticipantRecord))
        assert participant is not None
        assert participant.display_label == "Alice"
        assert participant.is_self is True
        assert participant.muted is True
        assert participant.hand_raised is True

    tables = set(inspect(database.engine).get_table_names())
    assert "evidence_events" not in tables
    database.dispose()


def test_speaker_registry_cascade_model_compatibility_and_manual_track_scope(
    tmp_path: Path,
) -> None:
    database, session_id, segment_id, _source_id, epoch_id = _semantic_database(
        tmp_path / "speakers.sqlite3"
    )
    registry = SpeakerRegistry(database)
    profile = registry.create("Alice", aliases=("Al", " AL "))
    assert profile.aliases == ("Al",)
    registry.add_prototype(
        profile.id,
        model_id="speaker-model",
        model_version="1",
        dimensions=2,
        embedding=b"\0" * 8,
        quality=0.9,
        speech_duration_ms=2_000,
        source_type="manual",
        consent_provenance="explicit_ui",
    )
    try:
        registry.add_prototype(
            profile.id,
            model_id="other-model",
            model_version="1",
            dimensions=2,
            embedding=b"\0" * 8,
            quality=0.9,
            speech_duration_ms=2_000,
            source_type="manual",
            consent_provenance="explicit_ui",
        )
    except ValueError as exc:
        assert "compatible model" in str(exc)
    else:
        raise AssertionError("incompatible prototype was accepted")
    registry.link_semantic_identity(
        profile.id,
        identity_kind="browser_participant",
        identity_digest="a" * 64,
        confidence=1.0,
        provenance="manual",
    )

    with database.transaction() as db:
        utterances = [
            UtteranceRecord(
                session_id=session_id,
                segment_id=segment_id,
                source_epoch_id=epoch_id,
                utterance_id=f"u-{index}",
                revision=1,
                text=f"text {index}",
                first_session_offset_us=index,
                last_session_offset_us=index,
            )
            for index in range(2)
        ]
        db.add_all(utterances)
        db.flush()
        db.add_all(
            [
                UtteranceSpeakerAssignmentRecord(
                    utterance_id=item.id,
                    anonymous_track_id="track-1",
                    speaker_role="unknown",
                    confidence=0.0,
                )
                for item in utterances
            ]
        )
        first_id = utterances[0].id

    assert (
        assign_speaker_manually(
            database,
            first_id,
            profile_id=profile.id,
            display_label=None,
            apply_to_anonymous_track=True,
            use_voice_samples=False,
        )
        == 2
    )
    with database.transaction() as db:
        assignments = list(db.scalars(select(UtteranceSpeakerAssignmentRecord)))
        assert {item.display_label for item in assignments} == {"Alice"}
        assert {item.speaker_profile_id for item in assignments} == {profile.id}

    assert registry.delete(profile.id) is True
    with database.transaction() as db:
        assignments = list(db.scalars(select(UtteranceSpeakerAssignmentRecord)))
        assert {item.speaker_profile_id for item in assignments} == {None}
        assert db.scalar(select(SpeakerPrototypeRecord)) is None
        assert db.scalar(select(SpeakerProfileAliasRecord)) is None
        assert db.scalar(select(SpeakerSemanticIdentityRecord)) is None
    database.dispose()
