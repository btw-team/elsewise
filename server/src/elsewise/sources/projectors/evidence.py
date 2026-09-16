from collections.abc import Callable, Mapping
from datetime import datetime
from hashlib import sha256
from time import monotonic_ns
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from elsewise.evidence import EvidenceBus, EvidenceEvent, PublishResult
from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    ActivityParticipantRecord,
    ActivityRecord,
    ActivitySourceLinkRecord,
    CaptureSourceRecord,
    EvidenceEventCounterRecord,
    EvidenceEventDiagnosticRecord,
    EvidenceEventTombstoneRecord,
    SessionRecord,
    SessionSourceBindingRecord,
    SourceEpochRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
    utc_now,
)
from elsewise.protocol.models import EvidenceEmit
from elsewise.services.outbox import emit_ui_event
from elsewise.services.speaker_identity import classify_speaker, own_speaker_names
from elsewise.settings.config import SettingsStore

ALLOWED_KINDS: dict[str, frozenset[str]] = {
    "activity_lifecycle": frozenset(
        {"activity.detected", "activity.started", "activity.ended"}
    ),
    "participants": frozenset({"participant.upsert", "participant.left"}),
    "self_identity": frozenset({"participant.self"}),
    "active_speaker": frozenset({"speaker.started", "speaker.stopped"}),
    "captions": frozenset({"caption.partial", "caption.final", "caption.retracted"}),
    "mute_state": frozenset({"participant.muted", "participant.unmuted"}),
    "hand_raise": frozenset({"participant.hand_raised", "participant.hand_lowered"}),
    "reactions": frozenset({"participant.reaction"}),
    "presentation": frozenset(
        {"presentation.started", "presentation.changed", "presentation.stopped"}
    ),
    "chat": frozenset({"chat.message"}),
    "recording_state": frozenset({"recording.started", "recording.stopped"}),
}


class EvidenceProjector:
    def __init__(
        self,
        database: Database,
        bus: EvidenceBus | None = None,
        settings: SettingsStore | None = None,
        *,
        monotonic_us: Callable[[], int] | None = None,
    ) -> None:
        self.database = database
        self.bus = bus or EvidenceBus()
        self.settings = settings
        self._monotonic_us = monotonic_us or (lambda: monotonic_ns() // 1_000)
        self._clock_anchors: dict[str, tuple[int, int]] = {}

    def process(self, message: EvidenceEmit) -> str:
        event_id = str(message.event_id)
        epoch_id = str(message.source_epoch_id)
        source_id = str(message.source_id)
        received_at = utc_now()
        event: EvidenceEvent | None = None
        result = "applied"
        reason: str | None = None

        with self.database.transaction() as db:
            if db.get(EvidenceEventTombstoneRecord, event_id) is not None:
                return "duplicate"
            epoch = db.get(SourceEpochRecord, epoch_id)
            source = db.get(CaptureSourceRecord, epoch.source_id) if epoch else None
            session = (
                db.get(SessionRecord, epoch.session_id)
                if epoch and epoch.session_id
                else None
            )
            if epoch is None or epoch.source_id != source_id or source is None:
                result, reason = "source_not_bound", "source_not_bound"
            elif session is None or session.recording_status not in {"running", "stopping"}:
                result, reason = "no_active_session", "no_active_session"
            elif epoch.state not in {"starting", "running", "stopping"}:
                result, reason = "source_not_bound", "epoch_not_running"
            elif message.capability not in source.capabilities:
                result, reason = "rejected", "capability_not_advertised"
            elif message.kind not in ALLOWED_KINDS.get(message.capability, frozenset()):
                result, reason = "rejected", "unsupported_evidence_kind"
            elif message.interval_end_us < message.interval_start_us:
                result, reason = "rejected", "invalid_interval"
            else:
                start_us = self._session_offset_us(
                    message.source_time_us,
                    message.interval_start_us,
                    session,
                    epoch_id,
                )
                end_us = self._session_offset_us(
                    message.source_time_us,
                    message.interval_end_us,
                    session,
                    epoch_id,
                )
                if session.recording_status == "stopping" and (
                    session.stop_boundary_offset_us is None
                    or start_us > session.stop_boundary_offset_us
                ):
                    result, reason = "rejected", "after_stop_boundary"
                else:
                    try:
                        event = EvidenceEvent(
                            event_id=event_id,
                            source_id=source_id,
                            source_epoch_id=epoch_id,
                            capability=message.capability,
                            kind=message.kind,
                            interval_start_us=start_us,
                            interval_end_us=max(start_us, end_us),
                            observed_monotonic_us=self._monotonic_us(),
                            timing_uncertainty_us=message.timing_uncertainty_us,
                            provenance=message.provenance,
                            confidence=message.confidence,
                            payload=message.payload,
                        )
                        if message.kind.startswith("caption."):
                            result, reason = self._project_caption(
                                db, session, source, epoch, event, message
                            )
                        elif message.kind.startswith("activity."):
                            self._project_activity(db, session, source, event)
                        elif message.kind.startswith("participant."):
                            self._project_participant(db, session, source, event)
                        elif message.kind.startswith(("presentation.", "recording.")):
                            self._project_activity_state(db, session, source, event)
                    except (TypeError, ValueError) as exc:
                        result, reason = "rejected", "invalid_evidence_payload"
                        log_event("evidence.invalid", source_id=source_id, error=type(exc).__name__)

            if epoch is not None:
                epoch.last_seen_at = received_at
                if result == "applied":
                    epoch.received_event_count += 1
                else:
                    epoch.rejected_event_count += 1
            self._record_result(
                db,
                message,
                result=result,
                reason=reason or result,
                received_at=received_at,
            )

        if event is not None and result == "applied":
            published = self.bus.publish(event)
            if published is PublishResult.DUPLICATE:
                return "duplicate"
        return result

    def _session_offset_us(
        self,
        observed_source_us: int,
        value_source_us: int,
        session: SessionRecord,
        epoch_id: str,
    ) -> int:
        daemon_now_us = self._monotonic_us()
        source_anchor, daemon_anchor = self._clock_anchors.setdefault(
            epoch_id, (observed_source_us, daemon_now_us)
        )
        mapped_daemon_us = daemon_anchor + (value_source_us - source_anchor)
        origin_us = (session.monotonic_origin_ns or daemon_now_us * 1_000) // 1_000
        return max(0, mapped_daemon_us - origin_us)

    def _project_caption(
        self,
        db: Session,
        session: SessionRecord,
        source: CaptureSourceRecord,
        epoch: SourceEpochRecord,
        event: EvidenceEvent,
        message: EvidenceEmit,
    ) -> tuple[str, str | None]:
        utterance_id = self._string(message.payload, "utterance_id", 256)
        revision = self._integer(message.payload, "revision", minimum=1)
        existing = db.scalar(
            select(UtteranceRecord).where(
                UtteranceRecord.source_epoch_id == epoch.id,
                UtteranceRecord.utterance_id == utterance_id,
            )
        )
        if message.kind == "caption.retracted":
            if existing is not None and not existing.final:
                db.delete(existing)
            return "applied", None
        text = self._string(message.payload, "text", 4_096)
        speaker = self._optional_string(message.payload, "speaker", 512)
        if self._native_primary_healthy(
            db, session.id, self._caption_role(speaker, source.platform)
        ):
            return "applied", "native_primary_healthy"
        if existing is not None and existing.final:
            return "stale", "final_utterance_immutable"
        if existing is not None and (
            revision < existing.revision
            or (revision == existing.revision and message.kind != "caption.final")
        ):
            return "stale", "stale_revision"
        final = message.kind == "caption.final"
        received_at = utc_now()
        if existing is None:
            existing = UtteranceRecord(
                session_id=session.id,
                segment_id=epoch.segment_id,
                source_epoch_id=epoch.id,
                utterance_id=utterance_id,
                revision=revision,
                text=text,
                final=final,
                origin_kind="browser_semantic_caption",
                origin_confidence=event.confidence,
                projection_version=2,
                first_session_offset_us=event.interval_start_us,
                last_session_offset_us=event.interval_end_us,
                first_received_at=received_at,
                last_received_at=received_at,
                first_client_seq=message.client_seq,
                last_client_seq=message.client_seq,
                finalization_state="durable_final" if final else "partial",
                provenance={"evidence_event_id": event.event_id, "evidence_kind": event.kind},
            )
            db.add(existing)
            db.flush()
            ui_type = "utterance.finalized" if final else "utterance.created"
        else:
            existing.revision = revision
            existing.text = text
            existing.last_session_offset_us = max(
                existing.last_session_offset_us, event.interval_end_us
            )
            existing.last_received_at = received_at
            existing.last_client_seq = message.client_seq
            existing.final = final
            existing.finalization_state = "durable_final" if final else "partial"
            existing.provenance = {
                "evidence_event_id": event.event_id,
                "evidence_kind": event.kind,
            }
            ui_type = "utterance.finalized" if final else "utterance.updated"
        assignment = self._upsert_speaker_assignment(
            db,
            existing,
            label=speaker,
            platform=source.platform,
            evidence_event_id=event.event_id,
        )
        emit_ui_event(
            db,
            ui_type,
            existing.id,
            self._utterance_payload(existing, assignment, source.id),
        )
        return "applied", None

    def _project_activity(
        self,
        db: Session,
        session: SessionRecord,
        source: CaptureSourceRecord,
        event: EvidenceEvent,
    ) -> ActivityRecord:
        external_key = (
            self._optional_string(event.payload, "activity_key", 256) or source.activity_key
        )
        digest = sha256(f"{source.id}:{external_key or 'current'}".encode()).hexdigest()
        activity = db.scalar(
            select(ActivityRecord)
            .where(
                ActivityRecord.session_id == session.id,
                ActivityRecord.activity_key_digest == digest,
            )
            .order_by(ActivityRecord.created_at.desc())
        )
        if activity is None:
            activity = ActivityRecord(
                session_id=session.id,
                activity_key_digest=digest,
                state="detected",
                started_offset_us=event.interval_start_us,
                confidence=event.confidence,
                provenance=event.provenance,
            )
            db.add(activity)
            db.flush()
        if event.kind == "activity.started":
            activity.state = "running"
            activity.started_offset_us = min(activity.started_offset_us, event.interval_start_us)
        elif event.kind == "activity.ended":
            activity.state = "ended"
            activity.ended_offset_us = event.interval_end_us
        activity.confidence = max(activity.confidence, event.confidence)
        activity.provenance = event.provenance
        link = db.scalar(
            select(ActivitySourceLinkRecord).where(
                ActivitySourceLinkRecord.activity_id == activity.id,
                ActivitySourceLinkRecord.source_id == source.id,
            )
        )
        if link is None:
            db.add(
                ActivitySourceLinkRecord(
                    activity_id=activity.id,
                    source_id=source.id,
                    first_observed_offset_us=event.interval_start_us,
                    last_observed_offset_us=event.interval_end_us,
                    confidence=event.confidence,
                    provenance=event.provenance,
                )
            )
        else:
            link.last_observed_offset_us = max(
                link.last_observed_offset_us, event.interval_end_us
            )
            link.confidence = max(link.confidence, event.confidence)
        return activity

    def _project_participant(
        self,
        db: Session,
        session: SessionRecord,
        source: CaptureSourceRecord,
        event: EvidenceEvent,
    ) -> None:
        activity = db.scalar(
            select(ActivityRecord)
            .join(ActivitySourceLinkRecord)
            .where(
                ActivityRecord.session_id == session.id,
                ActivitySourceLinkRecord.source_id == source.id,
                ActivityRecord.state != "ended",
            )
            .order_by(ActivityRecord.created_at.desc())
        )
        if activity is None:
            synthetic_event = EvidenceEvent(
                event_id=event.event_id,
                source_id=event.source_id,
                source_epoch_id=event.source_epoch_id,
                capability="activity_lifecycle",
                kind="activity.detected",
                interval_start_us=event.interval_start_us,
                interval_end_us=event.interval_end_us,
                observed_monotonic_us=event.observed_monotonic_us,
                timing_uncertainty_us=event.timing_uncertainty_us,
                provenance=event.provenance,
                confidence=event.confidence,
                payload={},
            )
            activity = self._project_activity(db, session, source, synthetic_event)
        participant_key = self._string(event.payload, "participant_id", 256)
        identity_digest = sha256(f"{source.id}:{participant_key}".encode()).hexdigest()
        participant = db.scalar(
            select(ActivityParticipantRecord).where(
                ActivityParticipantRecord.activity_id == activity.id,
                ActivityParticipantRecord.identity_digest == identity_digest,
            )
        )
        if participant is None:
            participant = ActivityParticipantRecord(
                activity_id=activity.id,
                identity_digest=identity_digest,
                display_label=self._optional_string(event.payload, "display_label", 512),
                is_self=event.kind == "participant.self",
                presence_state="present",
                confidence=event.confidence,
                provenance=event.provenance,
                last_observed_offset_us=event.interval_end_us,
            )
            db.add(participant)
        else:
            label = self._optional_string(event.payload, "display_label", 512)
            if label is not None:
                participant.display_label = label
            participant.is_self = participant.is_self or event.kind == "participant.self"
            participant.presence_state = "left" if event.kind == "participant.left" else "present"
            participant.confidence = max(participant.confidence, event.confidence)
            participant.provenance = event.provenance
            participant.last_observed_offset_us = max(
                participant.last_observed_offset_us, event.interval_end_us
            )
        if event.kind in {"participant.muted", "participant.unmuted"}:
            participant.muted = event.kind == "participant.muted"
        if event.kind in {"participant.hand_raised", "participant.hand_lowered"}:
            participant.hand_raised = event.kind == "participant.hand_raised"

    def _project_activity_state(
        self,
        db: Session,
        session: SessionRecord,
        source: CaptureSourceRecord,
        event: EvidenceEvent,
    ) -> None:
        synthetic_event = EvidenceEvent(
            event_id=event.event_id,
            source_id=event.source_id,
            source_epoch_id=event.source_epoch_id,
            capability="activity_lifecycle",
            kind="activity.detected",
            interval_start_us=event.interval_start_us,
            interval_end_us=event.interval_end_us,
            observed_monotonic_us=event.observed_monotonic_us,
            timing_uncertainty_us=event.timing_uncertainty_us,
            provenance=event.provenance,
            confidence=event.confidence,
            payload=event.payload,
        )
        activity = self._project_activity(db, session, source, synthetic_event)
        if event.kind.startswith("presentation."):
            activity.presentation_state = (
                "stopped" if event.kind == "presentation.stopped" else "active"
            )
        else:
            activity.recording_state = (
                "stopped" if event.kind == "recording.stopped" else "active"
            )

    @staticmethod
    def _record_result(
        db: Session,
        message: EvidenceEmit,
        *,
        result: str,
        reason: str,
        received_at: datetime,
    ) -> None:
        db.add(
            EvidenceEventTombstoneRecord(
                event_id=str(message.event_id),
                processing_result=result,
                received_at=received_at,
            )
        )
        counter = db.scalar(
            select(EvidenceEventCounterRecord).where(
                EvidenceEventCounterRecord.capability == message.capability,
                EvidenceEventCounterRecord.event_kind == message.kind,
                EvidenceEventCounterRecord.processing_result == result,
                EvidenceEventCounterRecord.reason_code == reason,
                EvidenceEventCounterRecord.protocol_version == message.protocol_version,
            )
        )
        if counter is None:
            db.add(
                EvidenceEventCounterRecord(
                    capability=message.capability,
                    event_kind=message.kind,
                    processing_result=result,
                    reason_code=reason,
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
                EvidenceEventDiagnosticRecord(
                    event_id=str(message.event_id),
                    source_id=str(message.source_id),
                    capability=message.capability,
                    event_kind=message.kind,
                    processing_result=result,
                    reason_code=reason,
                    protocol_version=message.protocol_version,
                    received_at=received_at,
                )
            )

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
        if source is None or source.driver_id != "native_audio" or not source.connected:
            return False
        return (
            db.scalar(
                select(SourceEpochRecord).where(
                    SourceEpochRecord.binding_id == binding.id,
                    SourceEpochRecord.state == "running",
                    SourceEpochRecord.effective_backend.is_not(None),
                    SourceEpochRecord.last_health_status == "available",
                )
            )
            is not None
        )

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
        elif not assignment.provenance.startswith("manual") and (
            assignment.display_label != label or assignment.speaker_role != role
        ):
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

    @staticmethod
    def _string(payload: Mapping[str, Any], key: str, maximum: int) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise ValueError(f"{key} is invalid")
        return value

    @classmethod
    def _optional_string(
        cls, payload: Mapping[str, Any], key: str, maximum: int
    ) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        return cls._string(payload, key, maximum)

    @staticmethod
    def _integer(payload: Mapping[str, Any], key: str, *, minimum: int) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{key} is invalid")
        return value
