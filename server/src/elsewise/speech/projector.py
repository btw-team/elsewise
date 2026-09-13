from sqlalchemy import select

from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    SessionRecord,
    SessionSourceBindingRecord,
    SourceEpochRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
    utc_now,
)
from elsewise.services.outbox import emit_ui_event
from elsewise.speech.contracts import ASRBackend, SpeechEvent

CANONICAL_SAMPLE_RATE = 16_000


class SpeechProjector:
    def __init__(self, database: Database) -> None:
        self.database = database

    def process(self, epoch_id: str, event: SpeechEvent, backend: ASRBackend) -> str:
        received_at = utc_now()
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, epoch_id)
            binding = (
                db.get(SessionSourceBindingRecord, epoch.binding_id)
                if epoch is not None and epoch.binding_id is not None
                else None
            )
            session = (
                db.get(SessionRecord, epoch.session_id)
                if epoch is not None and epoch.session_id is not None
                else None
            )
            if (
                epoch is None
                or binding is None
                or session is None
                or epoch.segment_id is None
                or session.recording_status not in {"running", "stopping"}
                or epoch.state not in {"starting", "running", "stopping"}
            ):
                return "source_not_bound"
            record = db.scalar(
                select(UtteranceRecord).where(
                    UtteranceRecord.source_epoch_id == epoch.id,
                    UtteranceRecord.utterance_id == event.utterance_id,
                )
            )
            if record is not None and record.finalization_state == "durable_final":
                return "final_utterance_immutable"
            if record is not None and event.revision <= record.revision:
                return "stale"
            first_offset = epoch.session_offset_base_us + (
                event.first_sample_position * 1_000_000 // CANONICAL_SAMPLE_RATE
            )
            last_offset = epoch.session_offset_base_us + (
                event.last_sample_position * 1_000_000 // CANONICAL_SAMPLE_RATE
            )
            final = event.kind == "final"
            finalization_state = (
                "durable_final" if event.durable else "live_final" if final else "partial"
            )
            assignment: UtteranceSpeakerAssignmentRecord
            if record is None:
                record = UtteranceRecord(
                    session_id=session.id,
                    segment_id=epoch.segment_id,
                    source_epoch_id=epoch.id,
                    utterance_id=event.utterance_id,
                    revision=event.revision,
                    text=event.text,
                    final=final,
                    origin_kind="native_asr",
                    origin_confidence=event.confidence if event.confidence is not None else 1.0,
                    projection_version=1,
                    first_session_offset_us=first_offset,
                    last_session_offset_us=last_offset,
                    first_received_at=received_at,
                    last_received_at=received_at,
                    first_audio_sample_position=event.first_sample_position,
                    last_audio_sample_position=event.last_sample_position,
                    finalization_state=finalization_state,
                    asr_backend=backend.id,
                    asr_model_id=backend.model_id,
                    asr_model_version=backend.model_version,
                    transcript_confidence=event.confidence,
                    provenance={"kind": "native_audio", "source_role": binding.role},
                )
                db.add(record)
                db.flush()
                assignment = UtteranceSpeakerAssignmentRecord(
                    utterance_id=record.id,
                    revision=1,
                    speaker_role="self" if binding.role == "self" else "remote",
                    display_label="You" if binding.role == "self" else "Speaker 1",
                    anonymous_track_id=None if binding.role == "self" else "remote-1",
                    confidence=1.0,
                    evidence_refs=[],
                    provenance="audio.topology",
                )
                db.add(assignment)
                ui_type = "utterance.finalized" if final else "utterance.created"
            else:
                record.revision = event.revision
                record.text = event.text
                record.final = final
                record.last_session_offset_us = last_offset
                record.last_received_at = received_at
                record.last_audio_sample_position = event.last_sample_position
                record.finalization_state = finalization_state
                record.transcript_confidence = event.confidence
                existing_assignment = db.scalar(
                    select(UtteranceSpeakerAssignmentRecord).where(
                        UtteranceSpeakerAssignmentRecord.utterance_id == record.id
                    )
                )
                if existing_assignment is None:
                    assignment = UtteranceSpeakerAssignmentRecord(
                        utterance_id=record.id,
                        revision=1,
                        speaker_role="self" if binding.role == "self" else "remote",
                        display_label="You" if binding.role == "self" else "Speaker 1",
                        anonymous_track_id=None if binding.role == "self" else "remote-1",
                        confidence=1.0,
                        evidence_refs=[],
                        provenance="audio.topology",
                    )
                    db.add(assignment)
                else:
                    assignment = existing_assignment
                ui_type = "utterance.finalized" if final else "utterance.updated"
            emit_ui_event(
                db,
                ui_type,
                record.id,
                {
                    "id": record.id,
                    "session_id": record.session_id,
                    "segment_id": record.segment_id,
                    "source_epoch_id": record.source_epoch_id,
                    "utterance_id": record.utterance_id,
                    "revision": record.revision,
                    "speaker": assignment.display_label,
                    "speaker_role": assignment.speaker_role,
                    "text": record.text,
                    "final": record.final,
                    "first_session_offset_us": record.first_session_offset_us,
                    "last_session_offset_us": record.last_session_offset_us,
                    "first_client_seq": None,
                    "last_client_seq": None,
                    "first_audio_sample_position": record.first_audio_sample_position,
                    "last_audio_sample_position": record.last_audio_sample_position,
                    "finalization_state": record.finalization_state,
                },
            )
            return "applied"
