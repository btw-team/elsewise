from collections.abc import Callable
from time import monotonic_ns

from sqlalchemy import select
from sqlalchemy.orm import Session

from elsewise.evidence.contracts import EvidenceEvent
from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptionEventCounterRecord,
    CaptionEventDiagnosticRecord,
    CaptionEventTombstoneRecord,
    CaptureSourceRecord,
    SessionRecord,
    SessionSourceBindingRecord,
    SourceEpochRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
    utc_now,
)
from elsewise.protocol.models import CaptionFinalize, CaptionUpsert
from elsewise.services.outbox import emit_ui_event
from elsewise.services.speaker_identity import classify_speaker, own_speaker_names
from elsewise.settings.config import SettingsStore


class CaptionProjector:
    def __init__(
        self,
        database: Database,
        settings: SettingsStore | None = None,
        monotonic_us: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self._monotonic_us = monotonic_us or (lambda: monotonic_ns() // 1_000)
        self._clock_anchors: dict[str, tuple[int, int]] = {}

    def _session_offset_us(
        self,
        message: CaptionUpsert | CaptionFinalize,
        session: SessionRecord,
    ) -> int:
        daemon_now_us = self._monotonic_us()
        mapped_daemon_us = daemon_now_us
        if message.source_time_us is not None:
            source_anchor, daemon_anchor = self._clock_anchors.setdefault(
                str(message.source_epoch_id),
                (message.source_time_us, daemon_now_us),
            )
            mapped_daemon_us = daemon_anchor + max(0, message.source_time_us - source_anchor)
        origin_us = (session.monotonic_origin_ns or daemon_now_us * 1_000) // 1_000
        return max(0, mapped_daemon_us - origin_us)

    def process(self, message: CaptionUpsert | CaptionFinalize) -> str:
        received_at = utc_now()
        event_id = str(message.event_id)
        epoch_id = str(message.source_epoch_id)
        source_id = str(message.source_id)
        with self.database.transaction() as db:
            if db.get(CaptionEventTombstoneRecord, event_id) is not None:
                return "duplicate"

            epoch = db.get(SourceEpochRecord, epoch_id)
            source = db.get(CaptureSourceRecord, epoch.source_id) if epoch else None
            session = (
                db.get(SessionRecord, epoch.session_id) if epoch and epoch.session_id else None
            )
            session_offset_us = (
                self._session_offset_us(message, session) if session is not None else 0
            )
            result = "applied"
            reason: str | None = None
            if epoch is None or epoch.source_id != source_id:
                result, reason = "source_not_bound", "source_not_bound"
            elif session is None or session.recording_status not in {"running", "stopping"}:
                result, reason = "no_active_session", "no_active_session"
            elif session.recording_status == "stopping" and (
                session.stop_boundary_offset_us is None
                or session_offset_us > session.stop_boundary_offset_us
            ):
                result, reason = "rejected", "after_stop_boundary"
            elif epoch.state not in {"starting", "running", "stopping"}:
                result, reason = "source_not_bound", "epoch_not_running"
            elif session is not None and self._native_primary_healthy(
                db,
                session.id,
                self._caption_role(message.speaker, source.platform if source else "synthetic"),
            ):
                result, reason = "secondary_evidence", "native_primary_healthy"

            existing = db.scalar(
                select(UtteranceRecord).where(
                    UtteranceRecord.source_epoch_id == epoch_id,
                    UtteranceRecord.utterance_id == message.utterance_id,
                )
            )
            if result == "applied" and existing is not None and existing.final:
                result, reason = "rejected", "final_utterance_immutable"
            elif (
                result == "applied"
                and existing is not None
                and (
                    message.revision < existing.revision
                    or (
                        message.revision == existing.revision and isinstance(message, CaptionUpsert)
                    )
                )
            ):
                result, reason = "stale", "stale_revision"

            if result == "applied" and epoch is not None and session is not None:
                evidence = EvidenceEvent(
                    event_id=event_id,
                    source_id=source_id,
                    source_epoch_id=epoch_id,
                    capability="captions",
                    kind=message.type,
                    interval_start_us=session_offset_us,
                    interval_end_us=session_offset_us,
                    observed_monotonic_us=self._monotonic_us(),
                    timing_uncertainty_us=0,
                    provenance="browser.protocol.v2",
                    confidence=1.0,
                    payload={"utterance_id": message.utterance_id},
                )
                if existing is None:
                    existing = UtteranceRecord(
                        session_id=session.id,
                        segment_id=epoch.segment_id,
                        source_epoch_id=epoch.id,
                        utterance_id=message.utterance_id,
                        revision=message.revision,
                        text=message.text,
                        final=isinstance(message, CaptionFinalize),
                        origin_kind="browser_captions",
                        origin_confidence=1.0,
                        projection_version=1,
                        first_session_offset_us=session_offset_us,
                        last_session_offset_us=session_offset_us,
                        first_received_at=received_at,
                        last_received_at=received_at,
                        first_client_seq=message.client_seq,
                        last_client_seq=message.client_seq,
                        finalization_state=(
                            "durable_final" if isinstance(message, CaptionFinalize) else "partial"
                        ),
                        provenance={
                            "evidence_event_id": evidence.event_id,
                            "evidence_kind": evidence.kind,
                        },
                    )
                    db.add(existing)
                    db.flush()
                    ui_type = "utterance.finalized" if existing.final else "utterance.created"
                else:
                    existing.revision = message.revision
                    existing.text = message.text
                    existing.last_session_offset_us = max(
                        existing.last_session_offset_us, session_offset_us
                    )
                    existing.last_received_at = received_at
                    existing.last_client_seq = message.client_seq
                    existing.final = isinstance(message, CaptionFinalize)
                    existing.finalization_state = "durable_final" if existing.final else "partial"
                    existing.provenance = {
                        "evidence_event_id": evidence.event_id,
                        "evidence_kind": evidence.kind,
                    }
                    ui_type = "utterance.finalized" if existing.final else "utterance.updated"
                assignment = self._upsert_speaker_assignment(
                    db,
                    existing,
                    label=message.speaker,
                    platform=source.platform if source else "synthetic",
                    evidence_event_id=evidence.event_id,
                )
                epoch.last_seen_at = received_at
                epoch.received_event_count += 1
                emit_ui_event(
                    db,
                    ui_type,
                    existing.id,
                    self._utterance_payload(
                        existing,
                        assignment,
                        source_id,
                    ),
                )
            elif epoch is not None:
                epoch.rejected_event_count += 1

            reason_code = reason or result
            db.add(
                CaptionEventTombstoneRecord(
                    event_id=event_id,
                    processing_result=result,
                    received_at=received_at,
                )
            )
            counter = db.scalar(
                select(CaptionEventCounterRecord).where(
                    CaptionEventCounterRecord.event_type == message.type,
                    CaptionEventCounterRecord.processing_result == result,
                    CaptionEventCounterRecord.reason_code == reason_code,
                    CaptionEventCounterRecord.protocol_version == message.protocol_version,
                )
            )
            if counter is None:
                db.add(
                    CaptionEventCounterRecord(
                        event_type=message.type,
                        processing_result=result,
                        reason_code=reason_code,
                        protocol_version=message.protocol_version,
                        count=1,
                        first_received_at=received_at,
                        last_received_at=received_at,
                    )
                )
            else:
                counter.count += 1
                counter.last_received_at = received_at
            if result != "applied":
                db.add(
                    CaptionEventDiagnosticRecord(
                        event_id=event_id,
                        source_id=source_id,
                        event_type=message.type,
                        processing_result=result,
                        reason_code=reason_code,
                        protocol_version=message.protocol_version,
                        received_at=received_at,
                    )
                )
                log_event("caption.processed", source_id=source_id, result=result, reason=reason)
            return result

    def _caption_role(self, label: str | None, platform: str) -> str:
        classified = (
            classify_speaker(label, platform, own_speaker_names(self.settings.load()))
            if self.settings is not None
            else "unknown"
        )
        return "self" if classified == "self" else "remote"

    @staticmethod
    def _native_primary_healthy(db: Session, session_id: str, role: str) -> bool:
        binding = db.scalar(
            select(SessionSourceBindingRecord).where(
                SessionSourceBindingRecord.session_id == session_id,
                SessionSourceBindingRecord.role == role,
                SessionSourceBindingRecord.state == "active",
                SessionSourceBindingRecord.effective_mode == "native",
            )
        )
        if binding is None or binding.source_id is None:
            return False
        source = db.get(CaptureSourceRecord, binding.source_id)
        if (
            source is None
            or source.driver_id != "native_audio"
            or not source.connected
            or not source.available
        ):
            return False
        native_epoch = db.scalar(
            select(SourceEpochRecord)
            .where(
                SourceEpochRecord.binding_id == binding.id,
                SourceEpochRecord.state == "running",
                SourceEpochRecord.effective_backend.is_not(None),
                SourceEpochRecord.last_health_status == "available",
            )
            .order_by(SourceEpochRecord.started_at.desc())
        )
        return native_epoch is not None

    def _upsert_speaker_assignment(
        self,
        db: Session,
        record: UtteranceRecord,
        *,
        label: str | None,
        platform: str,
        evidence_event_id: str,
    ) -> UtteranceSpeakerAssignmentRecord:
        assignment = db.scalar(
            select(UtteranceSpeakerAssignmentRecord).where(
                UtteranceSpeakerAssignmentRecord.utterance_id == record.id
            )
        )
        classified = (
            classify_speaker(label, platform, own_speaker_names(self.settings.load()))
            if self.settings is not None
            else "unknown"
        )
        role = "remote" if classified == "other" else classified
        if assignment is None:
            assignment = UtteranceSpeakerAssignmentRecord(
                utterance_id=record.id,
                revision=1,
                speaker_role=role,
                display_label=label,
                confidence=1.0 if role != "unknown" else 0.0,
                evidence_refs=[evidence_event_id],
                provenance="browser.caption_label",
            )
            db.add(assignment)
        elif assignment.display_label != label or assignment.speaker_role != role:
            assignment.revision += 1
            assignment.speaker_role = role
            assignment.display_label = label
            assignment.confidence = 1.0 if role != "unknown" else 0.0
            assignment.evidence_refs = [evidence_event_id]
            assignment.provenance = "browser.caption_label"
        return assignment

    @staticmethod
    def _utterance_payload(
        record: UtteranceRecord,
        assignment: UtteranceSpeakerAssignmentRecord,
        source_id: str,
    ) -> dict[str, object]:
        return {
            "id": record.id,
            "session_id": record.session_id,
            "segment_id": record.segment_id,
            "source_id": source_id,
            "source_epoch_id": record.source_epoch_id,
            "utterance_id": record.utterance_id,
            "revision": record.revision,
            "speaker": assignment.display_label,
            "speaker_role": assignment.speaker_role,
            "text": record.text,
            "final": record.final,
            "first_session_offset_us": record.first_session_offset_us,
            "last_session_offset_us": record.last_session_offset_us,
            "first_received_at": record.first_received_at.isoformat(),
            "last_received_at": record.last_received_at.isoformat(),
            "first_client_seq": record.first_client_seq,
            "last_client_seq": record.last_client_seq,
            "first_audio_sample_position": record.first_audio_sample_position,
            "last_audio_sample_position": record.last_audio_sample_position,
            "finalization_state": record.finalization_state,
            "asr_backend": record.asr_backend,
            "asr_model_id": record.asr_model_id,
            "asr_model_version": record.asr_model_version,
            "transcript_confidence": record.transcript_confidence,
        }
