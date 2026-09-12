from collections.abc import Callable
from time import monotonic_ns

from sqlalchemy import select

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptionEventCounterRecord,
    CaptionEventDiagnosticRecord,
    CaptionEventTombstoneRecord,
    CaptureSourceRecord,
    SessionRecord,
    SourceEpochRecord,
    UtteranceRecord,
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
                if existing is None:
                    existing = UtteranceRecord(
                        session_id=session.id,
                        segment_id=epoch.segment_id,
                        source_epoch_id=epoch.id,
                        utterance_id=message.utterance_id,
                        revision=message.revision,
                        speaker=message.speaker,
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
                    )
                    db.add(existing)
                    ui_type = "utterance.finalized" if existing.final else "utterance.created"
                else:
                    existing.revision = message.revision
                    existing.speaker = message.speaker
                    existing.text = message.text
                    existing.last_session_offset_us = max(
                        existing.last_session_offset_us, session_offset_us
                    )
                    existing.last_received_at = received_at
                    existing.last_client_seq = message.client_seq
                    existing.final = isinstance(message, CaptionFinalize)
                    ui_type = "utterance.finalized" if existing.final else "utterance.updated"
                epoch.last_seen_at = received_at
                epoch.received_event_count += 1
                emit_ui_event(
                    db,
                    ui_type,
                    existing.id,
                    self._utterance_payload(
                        existing, source_id, source.platform if source else "synthetic"
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

    def _utterance_payload(
        self, record: UtteranceRecord, source_id: str, platform: str
    ) -> dict[str, object]:
        return {
            "id": record.id,
            "session_id": record.session_id,
            "segment_id": record.segment_id,
            "source_id": source_id,
            "source_epoch_id": record.source_epoch_id,
            "utterance_id": record.utterance_id,
            "revision": record.revision,
            "speaker": record.speaker,
            "speaker_role": (
                classify_speaker(record.speaker, platform, own_speaker_names(self.settings.load()))
                if self.settings is not None
                else "unknown"
            ),
            "text": record.text,
            "final": record.final,
            "first_session_offset_us": record.first_session_offset_us,
            "last_session_offset_us": record.last_session_offset_us,
            "first_received_at": record.first_received_at.isoformat(),
            "last_received_at": record.last_received_at.isoformat(),
            "first_client_seq": record.first_client_seq,
            "last_client_seq": record.last_client_seq,
        }
