from typing import Any

from elsewise.persistence.models import (
    CaptureSourceRecord,
    RecordingSegmentRecord,
    UiEventRecord,
    UtteranceRecord,
)
from elsewise.services.speaker_identity import SpeakerRole


def segment_payload(record: RecordingSegmentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "sequence": record.sequence,
        "started_at": record.started_at.isoformat(),
        "stopped_at": record.stopped_at.isoformat() if record.stopped_at else None,
        "stop_reason": record.stop_reason,
    }


def source_payload(
    record: CaptureSourceRecord,
    *,
    client_display_name: str | None = None,
    browser_family: str | None = None,
    tab_ordinal: int | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "paired_client_id": record.paired_client_id,
        "source_kind": record.source_kind,
        "platform": record.platform,
        "driver_id": record.driver_id,
        "driver_version": record.driver_version,
        "tab_instance_id": record.tab_instance_id,
        "capabilities": record.capabilities,
        "available": record.available,
        "connected": record.connected,
        "health_status": record.health_status,
        "last_error_code": record.last_error_code,
        "last_event_at": record.last_event_at.isoformat() if record.last_event_at else None,
        "client_display_name": client_display_name,
        "browser_family": browser_family,
        "tab_ordinal": tab_ordinal,
    }


def utterance_payload(
    record: UtteranceRecord, *, speaker_role: SpeakerRole = "unknown"
) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "segment_id": record.segment_id,
        "source_epoch_id": record.source_epoch_id,
        "utterance_id": record.utterance_id,
        "revision": record.revision,
        "speaker": record.speaker,
        "speaker_role": speaker_role,
        "text": record.text,
        "final": record.final,
        "first_session_offset_us": record.first_session_offset_us,
        "last_session_offset_us": record.last_session_offset_us,
        "first_received_at": record.first_received_at.isoformat(),
        "last_received_at": record.last_received_at.isoformat(),
        "first_client_seq": record.first_client_seq,
        "last_client_seq": record.last_client_seq,
    }


def ui_event_payload(record: UiEventRecord) -> dict[str, Any]:
    return {
        "type": "ui.event",
        "protocol_version": 2,
        "event_id": record.id,
        "event_type": record.event_type,
        "aggregate_id": record.aggregate_id,
        "created_at": record.created_at.isoformat(),
        "payload": record.payload,
    }
