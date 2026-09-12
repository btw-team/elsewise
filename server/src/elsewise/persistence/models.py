from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index(
            "uq_sessions_one_active",
            text("1"),
            unique=True,
            sqlite_where=text("recording_status IN ('starting', 'running', 'stopping')"),
        ),
        CheckConstraint(
            "recording_status IN ('starting', 'running', 'stopping', 'stopped')",
            name="ck_sessions_recording_status",
        ),
        CheckConstraint(
            "source_status IN ('no_source', 'waiting_for_source', "
            "'captions_not_detected', 'capturing', 'degraded')",
            name="ck_sessions_source_status",
        ),
        CheckConstraint(
            "stop_boundary_offset_us IS NULL OR stop_boundary_offset_us >= 0",
            name="ck_sessions_stop_boundary",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(32), default="ru")
    initial_prompt: Mapped[str] = mapped_column(Text, default="")
    action_preset_id: Mapped[str | None] = mapped_column(
        ForeignKey("action_presets.id", ondelete="SET NULL"), index=True
    )
    agent_provider: Mapped[str] = mapped_column(String(32), default="codex", index=True)
    agent_model: Mapped[str | None] = mapped_column(String(128))
    agent_reasoning_effort: Mapped[str | None] = mapped_column(String(32))
    recording_status: Mapped[str] = mapped_column(String(32), default="stopped", index=True)
    source_status: Mapped[str] = mapped_column(String(64), default="no_source")
    agent_status: Mapped[str] = mapped_column(String(32), default="not_started")
    requested_agent_cwd: Mapped[str | None] = mapped_column(Text)
    resolved_agent_cwd: Mapped[str | None] = mapped_column(Text)
    agent_cwd_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_workspace_write: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_network: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permission_audit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    selected_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("capture_sources.id", ondelete="SET NULL"), index=True
    )
    monotonic_origin_ns: Mapped[int | None] = mapped_column(Integer)
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_boundary_offset_us: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class RecordingSegmentRecord(Base):
    __tablename__ = "recording_segments"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="uq_segment_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_reason: Mapped[str | None] = mapped_column(String(128))
    first_client_seq: Mapped[int | None] = mapped_column(Integer)
    last_client_seq: Mapped[int | None] = mapped_column(Integer)
    first_utterance_id: Mapped[str | None] = mapped_column(String(256))
    last_utterance_id: Mapped[str | None] = mapped_column(String(256))


class CaptureSourceRecord(Base):
    __tablename__ = "capture_sources"
    __table_args__ = (
        CheckConstraint("protocol_version = 2", name="ck_capture_sources_protocol"),
        CheckConstraint(
            "health_status IN ('available', 'waiting', 'degraded', 'unavailable', 'failed')",
            name="ck_capture_sources_health",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paired_client_id: Mapped[str] = mapped_column(
        ForeignKey("paired_clients.id", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(64), default="browser_captions")
    platform: Mapped[str] = mapped_column(String(64))
    driver_id: Mapped[str] = mapped_column(String(128), default="browser_captions")
    driver_version: Mapped[str] = mapped_column(String(64), default="unknown")
    protocol_version: Mapped[int] = mapped_column(Integer, default=2)
    tab_instance_id: Mapped[str] = mapped_column(String(128), index=True)
    activity_key: Mapped[str | None] = mapped_column(String(256))
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(64), default="available")
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sanitized_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PairedClientRecord(Base):
    __tablename__ = "paired_clients"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_paired_clients_status"),
        CheckConstraint("length(credential_digest) = 64", name="ck_paired_clients_digest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    installation_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    browser_family: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(128))
    credential_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PairingRequestRecord(Base):
    __tablename__ = "pairing_requests"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'approved', 'denied', 'expired', 'cancelled')",
            name="ck_pairing_requests_state",
        ),
        CheckConstraint("length(nonce_digest) = 64", name="ck_pairing_requests_digest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    installation_id: Mapped[str] = mapped_column(String(36), index=True)
    browser_family: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(128))
    extension_version: Mapped[str] = mapped_column(String(64))
    nonce_digest: Mapped[str] = mapped_column(String(64), unique=True)
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceEpochRecord(Base):
    __tablename__ = "source_epochs"
    __table_args__ = (
        Index(
            "uq_source_epochs_one_running",
            "source_id",
            "session_id",
            unique=True,
            sqlite_where=text("state = 'running'"),
        ),
        CheckConstraint(
            "state IN ('starting', 'running', 'stopping', 'stopped', 'failed')",
            name="ck_source_epochs_state",
        ),
        CheckConstraint(
            "reconnect_count >= 0 AND producer_restart_count >= 0 "
            "AND transport_error_count >= 0 AND dropped_event_count >= 0 "
            "AND received_event_count >= 0 AND rejected_event_count >= 0",
            name="ck_source_epochs_counters",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("capture_sources.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    segment_id: Mapped[str | None] = mapped_column(
        ForeignKey("recording_segments.id", ondelete="CASCADE"), index=True
    )
    producer_epoch_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(128))
    last_health_status: Mapped[str] = mapped_column(String(64), default="available")
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0)
    producer_restart_count: Mapped[int] = mapped_column(Integer, default=0)
    transport_error_count: Mapped[int] = mapped_column(Integer, default=0)
    dropped_event_count: Mapped[int] = mapped_column(Integer, default=0)
    received_event_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_event_count: Mapped[int] = mapped_column(Integer, default=0)


class CaptionEventTombstoneRecord(Base):
    __tablename__ = "caption_event_tombstones"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processing_result: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class CaptionEventDiagnosticRecord(Base):
    __tablename__ = "caption_event_diagnostics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    source_id: Mapped[str] = mapped_column(String(256), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    processing_result: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str] = mapped_column(String(128), index=True)
    protocol_version: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class CaptionEventCounterRecord(Base):
    __tablename__ = "caption_event_counters"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "processing_result",
            "reason_code",
            "protocol_version",
            name="uq_caption_event_counter",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64))
    processing_result: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str] = mapped_column(String(128))
    protocol_version: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=0)
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UtteranceRecord(Base):
    __tablename__ = "utterances"
    __table_args__ = (
        UniqueConstraint("source_epoch_id", "utterance_id", name="uq_epoch_utterance"),
        CheckConstraint("revision >= 1", name="ck_utterances_revision"),
        CheckConstraint(
            "first_session_offset_us >= 0 AND last_session_offset_us >= first_session_offset_us",
            name="ck_utterances_offsets",
        ),
        CheckConstraint(
            "origin_confidence >= 0 AND origin_confidence <= 1",
            name="ck_utterances_origin_confidence",
        ),
        CheckConstraint("projection_version >= 1", name="ck_utterances_projection_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("recording_segments.id", ondelete="CASCADE"), index=True
    )
    source_epoch_id: Mapped[str] = mapped_column(
        ForeignKey("source_epochs.id", ondelete="CASCADE"), index=True
    )
    utterance_id: Mapped[str] = mapped_column(String(256))
    revision: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text)
    final: Mapped[bool] = mapped_column(Boolean, default=False)
    origin_kind: Mapped[str] = mapped_column(String(64), default="browser_captions")
    origin_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    projection_version: Mapped[int] = mapped_column(Integer, default=1)
    first_session_offset_us: Mapped[int] = mapped_column(Integer)
    last_session_offset_us: Mapped[int] = mapped_column(Integer)
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    first_client_seq: Mapped[int] = mapped_column(Integer)
    last_client_seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ButtonDefinitionRecord(Base):
    __tablename__ = "button_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    label: Mapped[str] = mapped_column(String(128))
    prompt_template: Mapped[str] = mapped_column(Text)
    context_strategy: Mapped[str] = mapped_column(String(64))
    context_value: Mapped[int | None] = mapped_column(Integer)
    hard_character_cap: Mapped[int] = mapped_column(Integer, default=50_000)
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ActionPresetRecord(Base):
    __tablename__ = "action_presets"
    __table_args__ = (
        Index(
            "uq_action_presets_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ActionPresetItemRecord(Base):
    __tablename__ = "action_preset_items"
    __table_args__ = (UniqueConstraint("preset_id", "position", name="uq_action_preset_position"),)

    preset_id: Mapped[str] = mapped_column(
        ForeignKey("action_presets.id", ondelete="CASCADE"), primary_key=True
    )
    button_id: Mapped[str] = mapped_column(
        ForeignKey("button_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class AgentThreadRecord(Base):
    __tablename__ = "agent_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(64), default="codex")
    external_thread_id: Mapped[str | None] = mapped_column(String(256))
    init_prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    init_prompt_snapshot: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="starting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completed_boundary: Mapped[str | None] = mapped_column(String(256))


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("session_id", "queue_sequence", name="uq_run_queue"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("agent_threads.id", ondelete="CASCADE"), index=True
    )
    button_id: Mapped[str | None] = mapped_column(
        ForeignKey("button_definitions.id", ondelete="SET NULL")
    )
    queue_sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    button_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved_prompt: Mapped[str] = mapped_column(Text)
    frozen_context: Mapped[str] = mapped_column(Text)
    context_strategy: Mapped[str] = mapped_column(String(64))
    context_start: Mapped[str | None] = mapped_column(String(256))
    context_end: Mapped[str | None] = mapped_column(String(256))
    session_language: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    reasoning_effort: Mapped[str | None] = mapped_column(String(32))
    cwd: Mapped[str] = mapped_column(Text)
    permissions_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    external_turn_id: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    usage_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentMessageRecord(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_message_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    message_type: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, default="")
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class UiEventRecord(Base):
    __tablename__ = "ui_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(256), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaintenanceStateRecord(Base):
    __tablename__ = "maintenance_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    ui_events_pruned_through: Mapped[int] = mapped_column(Integer, default=0)
    last_vacuum_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
