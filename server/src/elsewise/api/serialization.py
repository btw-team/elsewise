from typing import Any

from elsewise.persistence.models import (
    ActivityParticipantRecord,
    ActivityRecord,
    CaptureSourceRecord,
    RecordingSegmentRecord,
    UiEventRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
)
from elsewise.protocol.models import PROTOCOL_VERSION


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
        "source_category": record.source_category,
        "source_role": record.source_role,
        "target_key": record.target_key,
        "platform": record.platform,
        "driver_id": record.driver_id,
        "driver_version": record.driver_version,
        "protocol_version": record.protocol_version,
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
    record: UtteranceRecord,
    assignment: UtteranceSpeakerAssignmentRecord | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "segment_id": record.segment_id,
        "source_epoch_id": record.source_epoch_id,
        "utterance_id": record.utterance_id,
        "revision": record.revision,
        "speaker": assignment.display_label if assignment else None,
        "speaker_role": assignment.speaker_role if assignment else "unknown",
        "speaker_profile_id": assignment.speaker_profile_id if assignment else None,
        "speaker_assignment_revision": assignment.revision if assignment else None,
        "speaker_assignment_provenance": assignment.provenance if assignment else None,
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


def activity_payload(record: ActivityRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "state": record.state,
        "started_offset_us": record.started_offset_us,
        "ended_offset_us": record.ended_offset_us,
        "confidence": record.confidence,
        "provenance": record.provenance,
        "presentation_state": record.presentation_state,
        "recording_state": record.recording_state,
        "updated_at": record.updated_at.isoformat(),
    }


def participant_payload(record: ActivityParticipantRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "display_label": record.display_label,
        "is_self": record.is_self,
        "presence_state": record.presence_state,
        "muted": record.muted,
        "hand_raised": record.hand_raised,
        "confidence": record.confidence,
        "provenance": record.provenance,
        "last_observed_offset_us": record.last_observed_offset_us,
        "updated_at": record.updated_at.isoformat(),
    }


def ui_event_payload(record: UiEventRecord) -> dict[str, Any]:
    return {
        "type": "ui.event",
        "protocol_version": PROTOCOL_VERSION,
        "event_id": record.id,
        "event_type": record.event_type,
        "aggregate_id": record.aggregate_id,
        "created_at": record.created_at.isoformat(),
        "payload": record.payload,
    }
