from datetime import UTC, datetime

from sqlalchemy import select, update

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptionEventCounterRecord,
    CaptionEventDiagnosticRecord,
    CaptionEventTombstoneRecord,
    CaptureSourceRecord,
    RecordingSegmentRecord,
    SessionRecord,
    UtteranceRecord,
    utc_now,
)
from elsewise.protocol.models import SourceStatus, UtteranceFinalize, UtteranceUpsert
from elsewise.services.outbox import emit_ui_event
from elsewise.services.speaker_identity import classify_speaker, own_speaker_names
from elsewise.settings.config import SettingsStore


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class CaptureService:
    def __init__(self, database: Database, settings: SettingsStore | None = None) -> None:
        self.database = database
        self.settings = settings

    def update_source(
        self,
        message: SourceStatus,
        *,
        installation_id: str,
        adapter_version: str = "unknown",
    ) -> str:
        with self.database.transaction() as db:
            running = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running")
            )
            reconnecting_same_tab = False
            if (
                message.enabled
                and running is not None
                and running.active_source_id not in (None, message.source_id)
            ):
                active = db.get(CaptureSourceRecord, running.active_source_id)
                reconnecting_same_tab = bool(
                    active is not None
                    and message.tab_id is not None
                    and active.installation_id == installation_id
                    and active.tab_id == message.tab_id
                    and active.meeting_key == message.meeting_key
                )
                if not reconnecting_same_tab:
                    log_event(
                        "source.rejected",
                        source_id=message.source_id,
                        platform=message.platform,
                        reason="source_switch_rejected",
                    )
                    return "source_switch_rejected"
            source = db.get(CaptureSourceRecord, message.source_id)
            if source is None:
                source = CaptureSourceRecord(
                    source_id=message.source_id,
                    installation_id=installation_id,
                    platform=message.platform,
                )
                db.add(source)
            if message.enabled:
                db.execute(
                    update(CaptureSourceRecord)
                    .where(CaptureSourceRecord.source_id != message.source_id)
                    .values(enabled=False)
                )
            source.enabled = message.enabled
            source.connected = True
            source.tab_id = message.tab_id
            source.document_id = message.document_id
            source.platform = message.platform
            source.meeting_key = message.meeting_key
            source.meeting_title = message.meeting_title
            source.adapter_version = adapter_version
            source.protocol_version = message.protocol_version
            source.captions_status = message.captions_status
            source.speaker_detection = message.speaker_detection
            source.last_event_at = message.observed_at
            if running is not None and message.enabled:
                running.enabled_source_id = message.source_id
                running.active_source_id = message.source_id
                running.capture_status = (
                    "capturing"
                    if message.captions_status == "capturing"
                    else "captions_not_detected"
                )
                segment = db.scalar(
                    select(RecordingSegmentRecord).where(
                        RecordingSegmentRecord.session_id == running.id,
                        RecordingSegmentRecord.stopped_at.is_(None),
                    )
                )
                if segment is not None:
                    segment.source_id = message.source_id
            elif (
                running is not None
                and not message.enabled
                and running.active_source_id == message.source_id
            ):
                running.enabled_source_id = None
                running.active_source_id = None
                running.capture_status = "waiting_for_source"
            emit_ui_event(
                db,
                "source.status",
                message.source_id,
                message.model_dump(mode="json"),
            )
            log_event(
                "source.status",
                source_id=message.source_id,
                platform=message.platform,
                state=message.captions_status,
            )
            return "applied"

    def process_caption(self, message: UtteranceUpsert | UtteranceFinalize) -> str:
        received_at = utc_now()
        with self.database.transaction() as db:
            duplicate = db.scalar(
                select(CaptionEventTombstoneRecord.event_id).where(
                    CaptionEventTombstoneRecord.event_id == str(message.event_id)
                )
            )
            if duplicate is not None:
                return "duplicate"

            session = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running")
            )
            in_grace = False
            if session is None and isinstance(message, UtteranceFinalize):
                candidate = db.scalar(
                    select(SessionRecord)
                    .where(SessionRecord.recording_status == "stopped")
                    .order_by(SessionRecord.stopped_at.desc())
                )
                if (
                    candidate is not None
                    and candidate.finalize_grace_until is not None
                    and _aware(message.observed_at) <= _aware(candidate.finalize_grace_until)
                ):
                    session = candidate
                    in_grace = True

            result = "applied"
            reason: str | None = None
            segment: RecordingSegmentRecord | None = None
            existing: UtteranceRecord | None = None
            if session is None:
                result = "no_active_session"
            else:
                expected_source = (
                    session.finalize_grace_source_id if in_grace else session.active_source_id
                )
                if expected_source != message.source_id:
                    result = "source_not_bound" if not in_grace else "rejected"
                    reason = "source_not_bound"
                segment = db.scalar(
                    select(RecordingSegmentRecord)
                    .where(RecordingSegmentRecord.session_id == session.id)
                    .order_by(RecordingSegmentRecord.sequence.desc())
                )
                existing = db.scalar(
                    select(UtteranceRecord).where(
                        UtteranceRecord.source_id == message.source_id,
                        UtteranceRecord.utterance_id == message.utterance_id,
                    )
                )
                if result == "applied" and in_grace and (existing is None or existing.final):
                    result = "rejected"
                    reason = "grace_finalize_existing_partial_only"
                elif result == "applied" and existing is not None and existing.final:
                    result = "rejected"
                    reason = "final_correction_not_supported_v1"
                elif (
                    result == "applied"
                    and existing is not None
                    and message.revision < existing.revision
                ) or (
                    result == "applied"
                    and existing is not None
                    and message.revision == existing.revision
                    and isinstance(message, UtteranceUpsert)
                ):
                    result = "stale"

            if result == "applied" and session is not None and segment is not None:
                if existing is None:
                    existing = UtteranceRecord(
                        session_id=session.id,
                        segment_id=segment.id,
                        source_id=message.source_id,
                        utterance_id=message.utterance_id,
                        revision=message.revision,
                        speaker=message.speaker,
                        text=message.text,
                        final=isinstance(message, UtteranceFinalize),
                        first_observed_at=message.observed_at,
                        last_observed_at=message.observed_at,
                        first_received_at=received_at,
                        last_received_at=received_at,
                        first_client_seq=message.client_seq,
                        last_client_seq=message.client_seq,
                    )
                    db.add(existing)
                    ui_type = "utterance.finalized" if existing.final else "utterance.created"
                else:
                    existing.revision = message.revision
                    existing.speaker = message.speaker
                    existing.text = message.text
                    existing.last_observed_at = message.observed_at
                    existing.last_received_at = received_at
                    existing.last_client_seq = message.client_seq
                    existing.final = isinstance(message, UtteranceFinalize)
                    ui_type = "utterance.finalized" if existing.final else "utterance.updated"
                if segment.first_client_seq is None:
                    segment.first_client_seq = message.client_seq
                    segment.first_utterance_id = message.utterance_id
                segment.last_client_seq = message.client_seq
                segment.last_utterance_id = message.utterance_id
                if in_grace:
                    result = "grace_finalize_applied"
                emit_ui_event(
                    db,
                    ui_type,
                    existing.id,
                    {
                        "id": existing.id,
                        "session_id": session.id,
                        "segment_id": existing.segment_id,
                        "source_id": message.source_id,
                        "utterance_id": message.utterance_id,
                        "revision": message.revision,
                        "speaker": message.speaker,
                        "speaker_role": (
                            classify_speaker(
                                message.speaker,
                                message.platform,
                                own_speaker_names(self.settings.load()),
                            )
                            if self.settings is not None
                            else "unknown"
                        ),
                        "text": message.text,
                        "final": existing.final,
                        "first_observed_at": existing.first_observed_at.isoformat(),
                        "last_observed_at": existing.last_observed_at.isoformat(),
                        "first_client_seq": existing.first_client_seq,
                        "last_client_seq": existing.last_client_seq,
                    },
                )

            reason_code = reason or (
                "no_running_session" if result == "no_active_session" else result
            )
            db.add(
                CaptionEventTombstoneRecord(
                    event_id=str(message.event_id),
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
                counter = CaptionEventCounterRecord(
                    event_type=message.type,
                    processing_result=result,
                    reason_code=reason_code,
                    protocol_version=message.protocol_version,
                    count=1,
                    first_received_at=received_at,
                    last_received_at=received_at,
                )
                db.add(counter)
            else:
                counter.count += 1
                counter.last_received_at = received_at
            if result not in {"applied", "grace_finalize_applied"}:
                db.add(
                    CaptionEventDiagnosticRecord(
                        event_id=str(message.event_id),
                        source_id=message.source_id,
                        event_type=message.type,
                        processing_result=result,
                        reason_code=reason_code,
                        protocol_version=message.protocol_version,
                        received_at=received_at,
                    )
                )
            if result != "applied":
                log_event(
                    "caption.processed",
                    source_id=message.source_id,
                    result=result,
                    reason=reason,
                )
            return result
