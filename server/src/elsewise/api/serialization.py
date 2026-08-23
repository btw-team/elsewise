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
        "source_id": record.source_id,
        "started_at": record.started_at.isoformat(),
        "stopped_at": record.stopped_at.isoformat() if record.stopped_at else None,
        "stop_reason": record.stop_reason,
    }


def source_payload(record: CaptureSourceRecord) -> dict[str, Any]:
    return {
        "source_id": record.source_id,
        "installation_id": record.installation_id,
        "tab_id": record.tab_id,
        "document_id": record.document_id,
        "platform": record.platform,
        "meeting_key": record.meeting_key,
        "meeting_title": record.meeting_title,
        "enabled": record.enabled,
        "connected": record.connected,
        "captions_status": record.captions_status,
        "speaker_detection": record.speaker_detection,
        "last_event_at": record.last_event_at.isoformat() if record.last_event_at else None,
    }


def utterance_payload(
    record: UtteranceRecord, *, speaker_role: SpeakerRole = "unknown"
) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "segment_id": record.segment_id,
        "source_id": record.source_id,
        "utterance_id": record.utterance_id,
        "revision": record.revision,
        "speaker": record.speaker,
        "speaker_role": speaker_role,
        "text": record.text,
        "final": record.final,
        "first_observed_at": record.first_observed_at.isoformat(),
        "last_observed_at": record.last_observed_at.isoformat(),
        "first_client_seq": record.first_client_seq,
        "last_client_seq": record.last_client_seq,
    }


def ui_event_payload(record: UiEventRecord) -> dict[str, Any]:
    return {
        "type": "ui.event",
        "protocol_version": 1,
        "event_id": record.id,
        "event_type": record.event_type,
        "aggregate_id": record.aggregate_id,
        "created_at": record.created_at.isoformat(),
        "payload": record.payload,
    }
