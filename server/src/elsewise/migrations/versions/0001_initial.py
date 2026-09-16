"""Create the initial Elsewise schema and factory action library.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-18
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

from elsewise.services.builtin_actions import BUILTIN_ACTIONS, BUILTIN_PRESETS

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _factory_id(kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://github.com/btw-team/elsewise/{kind}/{value}"))


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "action_presets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "uq_action_presets_default",
        "action_presets",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
    )
    op.create_table(
        "button_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("context_strategy", sa.String(length=64), nullable=False),
        sa.Column("context_value", sa.Integer(), nullable=True),
        sa.Column("hard_character_cap", sa.Integer(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "paired_clients",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("browser_family", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("credential_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(credential_digest) = 64", name="ck_paired_clients_digest"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_paired_clients_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_paired_clients_installation_id",
        "paired_clients",
        ["installation_id"],
        unique=True,
    )
    op.create_index("ix_paired_clients_status", "paired_clients", ["status"])
    op.create_table(
        "pairing_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("browser_family", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("extension_version", sa.String(length=64), nullable=False),
        sa.Column("nonce_digest", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(nonce_digest) = 64", name="ck_pairing_requests_digest"),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'denied', 'expired', 'cancelled')",
            name="ck_pairing_requests_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nonce_digest"),
    )
    op.create_index("ix_pairing_requests_expires_at", "pairing_requests", ["expires_at"])
    op.create_index("ix_pairing_requests_installation_id", "pairing_requests", ["installation_id"])
    op.create_index("ix_pairing_requests_state", "pairing_requests", ["state"])
    op.create_table(
        "capture_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paired_client_id", sa.String(length=36), nullable=True),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("source_category", sa.String(length=32), nullable=False),
        sa.Column("source_role", sa.String(length=32), nullable=False),
        sa.Column("target_key", sa.String(length=256), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("driver_id", sa.String(length=128), nullable=False),
        sa.Column("driver_version", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("tab_instance_id", sa.String(length=128), nullable=True),
        sa.Column("activity_key", sa.String(length=256), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("connected", sa.Boolean(), nullable=False),
        sa.Column("health_status", sa.String(length=64), nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sanitized_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "health_status IN ('available', 'waiting', 'degraded', 'unavailable', 'failed')",
            name="ck_capture_sources_health",
        ),
        sa.CheckConstraint("protocol_version >= 1", name="ck_capture_sources_protocol"),
        sa.CheckConstraint(
            "source_category IN ('audio', 'semantic', 'synthetic')",
            name="ck_capture_sources_category",
        ),
        sa.CheckConstraint(
            "source_role IN ('self', 'remote', 'secondary')",
            name="ck_capture_sources_role",
        ),
        sa.CheckConstraint(
            "source_kind IN ('native_microphone', 'native_process_audio', "
            "'native_system_audio', 'browser_semantic', 'accessibility_macos', "
            "'accessibility_linux', 'accessibility_windows', 'synthetic_audio')",
            name="ck_capture_sources_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'browser_semantic' AND paired_client_id IS NOT NULL "
            "AND tab_instance_id IS NOT NULL AND source_category = 'semantic' "
            "AND source_role = 'secondary') OR "
            "(source_kind != 'browser_semantic' AND paired_client_id IS NULL "
            "AND tab_instance_id IS NULL)",
            name="ck_capture_sources_identity",
        ),
        sa.ForeignKeyConstraint(["paired_client_id"], ["paired_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capture_sources_paired_client_id", "capture_sources", ["paired_client_id"])
    op.create_index("ix_capture_sources_source_category", "capture_sources", ["source_category"])
    op.create_index("ix_capture_sources_source_role", "capture_sources", ["source_role"])
    op.create_index("ix_capture_sources_tab_instance_id", "capture_sources", ["tab_instance_id"])
    op.create_index("ix_capture_sources_target_key", "capture_sources", ["target_key"])
    op.create_table(
        "ui_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=256), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ui_events_aggregate_id", "ui_events", ["aggregate_id"])
    op.create_index("ix_ui_events_event_type", "ui_events", ["event_type"])
    op.create_table(
        "maintenance_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ui_events_pruned_through", sa.Integer(), nullable=False),
        sa.Column("last_vacuum_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "action_preset_items",
        sa.Column("preset_id", sa.String(length=36), nullable=False),
        sa.Column("button_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["button_id"], ["button_definitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preset_id"], ["action_presets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("preset_id", "button_id"),
        sa.UniqueConstraint("preset_id", "position", name="uq_action_preset_position"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("initial_prompt", sa.Text(), nullable=False),
        sa.Column("action_preset_id", sa.String(length=36), nullable=True),
        sa.Column("agent_provider", sa.String(length=32), nullable=False),
        sa.Column("agent_model", sa.String(length=128), nullable=True),
        sa.Column("agent_reasoning_effort", sa.String(length=32), nullable=True),
        sa.Column("recording_status", sa.String(length=32), nullable=False),
        sa.Column("source_status", sa.String(length=64), nullable=False),
        sa.Column("self_audio_enabled", sa.Boolean(), nullable=False),
        sa.Column("remote_audio_enabled", sa.Boolean(), nullable=False),
        sa.Column("secondary_fallback_enabled", sa.Boolean(), nullable=False),
        sa.Column("requested_speech_profile", sa.String(length=32), nullable=False),
        sa.Column("remote_target_key", sa.String(length=256), nullable=True),
        sa.Column("agent_status", sa.String(length=32), nullable=False),
        sa.Column("requested_agent_cwd", sa.Text(), nullable=True),
        sa.Column("resolved_agent_cwd", sa.Text(), nullable=True),
        sa.Column("agent_cwd_fallback", sa.Boolean(), nullable=False),
        sa.Column("allow_workspace_write", sa.Boolean(), nullable=False),
        sa.Column("allow_network", sa.Boolean(), nullable=False),
        sa.Column("permissions_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permission_audit", sa.JSON(), nullable=False),
        sa.Column("monotonic_origin_ns", sa.Integer(), nullable=True),
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_boundary_offset_us", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "recording_status IN ('starting', 'running', 'stopping', 'stopped')",
            name="ck_sessions_recording_status",
        ),
        sa.CheckConstraint(
            "source_status IN ('no_source', 'waiting_for_source', "
            "'captions_not_detected', 'capturing', 'degraded')",
            name="ck_sessions_source_status",
        ),
        sa.CheckConstraint(
            "stop_boundary_offset_us IS NULL OR stop_boundary_offset_us >= 0",
            name="ck_sessions_stop_boundary",
        ),
        sa.CheckConstraint(
            "requested_speech_profile IN ('auto', 'conservative', 'standard', 'best')",
            name="ck_sessions_speech_profile",
        ),
        sa.CheckConstraint(
            "self_audio_enabled = 1 OR remote_audio_enabled = 1 OR secondary_fallback_enabled = 1",
            name="ck_sessions_at_least_one_source_lane",
        ),
        sa.ForeignKeyConstraint(["action_preset_id"], ["action_presets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_action_preset_id", "sessions", ["action_preset_id"])
    op.create_index("ix_sessions_agent_provider", "sessions", ["agent_provider"])
    op.create_index("ix_sessions_recording_status", "sessions", ["recording_status"])
    op.create_index(
        "uq_sessions_one_active",
        "sessions",
        [sa.literal_column("1")],
        unique=True,
        sqlite_where=sa.text("recording_status IN ('starting', 'running', 'stopping')"),
    )
    op.create_table(
        "agent_threads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_thread_id", sa.String(length=256), nullable=True),
        sa.Column("init_prompt_version", sa.Integer(), nullable=False),
        sa.Column("init_prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_turn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_boundary", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_table(
        "recording_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(length=128), nullable=True),
        sa.Column("first_client_seq", sa.Integer(), nullable=True),
        sa.Column("last_client_seq", sa.Integer(), nullable=True),
        sa.Column("first_utterance_id", sa.String(length=256), nullable=True),
        sa.Column("last_utterance_id", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_segment_sequence"),
    )
    op.create_index("ix_recording_segments_session_id", "recording_segments", ["session_id"])
    op.create_table(
        "session_source_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("requested_mode", sa.String(length=32), nullable=False),
        sa.Column("effective_mode", sa.String(length=32), nullable=False),
        sa.Column("fallback_priority", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "effective_mode IN ('native', 'captions', 'synthetic', 'unavailable', 'disabled')",
            name="ck_session_source_bindings_effective_mode",
        ),
        sa.CheckConstraint(
            "fallback_priority >= 0", name="ck_session_source_bindings_fallback_priority"
        ),
        sa.CheckConstraint(
            "requested_mode IN ('auto', 'explicit', 'disabled')",
            name="ck_session_source_bindings_requested_mode",
        ),
        sa.CheckConstraint(
            "role IN ('self', 'remote', 'secondary')",
            name="ck_session_source_bindings_role",
        ),
        sa.CheckConstraint(
            "state IN ('starting', 'active', 'waiting', 'degraded', 'stopping', "
            "'stopped', 'disabled_by_user', 'failed')",
            name="ck_session_source_bindings_state",
        ),
        sa.ForeignKeyConstraint(["segment_id"], ["recording_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["capture_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_source_bindings_role", "session_source_bindings", ["role"])
    op.create_index(
        "ix_session_source_bindings_segment_id", "session_source_bindings", ["segment_id"]
    )
    op.create_index(
        "ix_session_source_bindings_session_id", "session_source_bindings", ["session_id"]
    )
    op.create_index(
        "ix_session_source_bindings_source_id", "session_source_bindings", ["source_id"]
    )
    op.create_index("ix_session_source_bindings_state", "session_source_bindings", ["state"])
    op.create_index(
        "uq_session_source_bindings_active_role",
        "session_source_bindings",
        ["session_id", "role"],
        unique=True,
        sqlite_where=sa.text("state IN ('starting', 'active', 'waiting', 'degraded', 'stopping')"),
    )
    op.create_table(
        "source_epochs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("segment_id", sa.String(length=36), nullable=True),
        sa.Column("producer_epoch_id", sa.String(length=128), nullable=False),
        sa.Column("session_offset_base_us", sa.Integer(), nullable=False),
        sa.Column("helper_instance_id", sa.String(length=128), nullable=True),
        sa.Column("helper_protocol_version", sa.Integer(), nullable=True),
        sa.Column("effective_format", sa.JSON(), nullable=False),
        sa.Column("effective_backend", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=128), nullable=True),
        sa.Column("last_health_status", sa.String(length=64), nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("reconnect_count", sa.Integer(), nullable=False),
        sa.Column("producer_restart_count", sa.Integer(), nullable=False),
        sa.Column("transport_error_count", sa.Integer(), nullable=False),
        sa.Column("dropped_event_count", sa.Integer(), nullable=False),
        sa.Column("received_event_count", sa.Integer(), nullable=False),
        sa.Column("rejected_event_count", sa.Integer(), nullable=False),
        sa.Column("first_sequence", sa.Integer(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=True),
        sa.Column("first_sample_position", sa.Integer(), nullable=True),
        sa.Column("last_sample_position", sa.Integer(), nullable=True),
        sa.Column("discontinuity_count", sa.Integer(), nullable=False),
        sa.Column("xrun_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "reconnect_count >= 0 AND producer_restart_count >= 0 "
            "AND transport_error_count >= 0 AND dropped_event_count >= 0 "
            "AND received_event_count >= 0 AND rejected_event_count >= 0 "
            "AND discontinuity_count >= 0 AND xrun_count >= 0",
            name="ck_source_epochs_counters",
        ),
        sa.CheckConstraint(
            "helper_protocol_version IS NULL OR helper_protocol_version >= 1",
            name="ck_source_epochs_helper_protocol",
        ),
        sa.CheckConstraint(
            "session_offset_base_us >= 0", name="ck_source_epochs_session_offset_base"
        ),
        sa.CheckConstraint(
            "first_sample_position IS NULL OR last_sample_position >= first_sample_position",
            name="ck_source_epochs_samples",
        ),
        sa.CheckConstraint(
            "first_sequence IS NULL OR last_sequence >= first_sequence",
            name="ck_source_epochs_sequences",
        ),
        sa.CheckConstraint(
            "state IN ('starting', 'running', 'stopping', 'stopped', 'failed')",
            name="ck_source_epochs_state",
        ),
        sa.ForeignKeyConstraint(["segment_id"], ["recording_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["capture_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["binding_id"], ["session_source_bindings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_epochs_segment_id", "source_epochs", ["segment_id"])
    op.create_index("ix_source_epochs_binding_id", "source_epochs", ["binding_id"])
    op.create_index("ix_source_epochs_session_id", "source_epochs", ["session_id"])
    op.create_index("ix_source_epochs_source_id", "source_epochs", ["source_id"])
    op.create_index("ix_source_epochs_state", "source_epochs", ["state"])
    op.create_index(
        "uq_source_epochs_one_running",
        "source_epochs",
        ["source_id", "session_id"],
        unique=True,
        sqlite_where=sa.text("state = 'running'"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("button_id", sa.String(length=36), nullable=True),
        sa.Column("queue_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("button_snapshot", sa.JSON(), nullable=False),
        sa.Column("resolved_prompt", sa.Text(), nullable=False),
        sa.Column("frozen_context", sa.Text(), nullable=False),
        sa.Column("context_strategy", sa.String(length=64), nullable=False),
        sa.Column("context_start", sa.String(length=256), nullable=True),
        sa.Column("context_end", sa.String(length=256), nullable=True),
        sa.Column("session_language", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("reasoning_effort", sa.String(length=32), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("permissions_snapshot", sa.JSON(), nullable=False),
        sa.Column("external_turn_id", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("usage_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["button_id"], ["button_definitions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "queue_sequence", name="uq_run_queue"),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_index("ix_agent_runs_thread_id", "agent_runs", ["thread_id"])
    op.create_table(
        "evidence_event_tombstones",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_evidence_event_tombstones_received_at",
        "evidence_event_tombstones",
        ["received_at"],
    )
    op.create_table(
        "evidence_event_diagnostics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("event_kind", sa.String(length=128), nullable=False),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_evidence_event_diagnostics_reason_code",
        "evidence_event_diagnostics",
        ["reason_code"],
    )
    op.create_index(
        "ix_evidence_event_diagnostics_received_at",
        "evidence_event_diagnostics",
        ["received_at"],
    )
    op.create_index(
        "ix_evidence_event_diagnostics_source_id",
        "evidence_event_diagnostics",
        ["source_id"],
    )
    op.create_table(
        "evidence_event_counters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("event_kind", sa.String(length=128), nullable=False),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capability",
            "event_kind",
            "processing_result",
            "reason_code",
            "protocol_version",
            name="uq_evidence_event_counter",
        ),
    )
    op.create_table(
        "utterances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("source_epoch_id", sa.String(length=36), nullable=False),
        sa.Column("utterance_id", sa.String(length=256), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("final", sa.Boolean(), nullable=False),
        sa.Column("origin_kind", sa.String(length=64), nullable=False),
        sa.Column("origin_confidence", sa.Float(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("first_session_offset_us", sa.Integer(), nullable=False),
        sa.Column("last_session_offset_us", sa.Integer(), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_client_seq", sa.Integer(), nullable=True),
        sa.Column("last_client_seq", sa.Integer(), nullable=True),
        sa.Column("first_audio_sample_position", sa.Integer(), nullable=True),
        sa.Column("last_audio_sample_position", sa.Integer(), nullable=True),
        sa.Column("finalization_state", sa.String(length=32), nullable=False),
        sa.Column("asr_backend", sa.String(length=128), nullable=True),
        sa.Column("asr_model_id", sa.String(length=256), nullable=True),
        sa.Column("asr_model_version", sa.String(length=128), nullable=True),
        sa.Column("transcript_confidence", sa.Float(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "first_session_offset_us >= 0 AND last_session_offset_us >= first_session_offset_us",
            name="ck_utterances_offsets",
        ),
        sa.CheckConstraint(
            "origin_confidence >= 0 AND origin_confidence <= 1",
            name="ck_utterances_origin_confidence",
        ),
        sa.CheckConstraint(
            "first_audio_sample_position IS NULL OR last_audio_sample_position "
            ">= first_audio_sample_position",
            name="ck_utterances_audio_samples",
        ),
        sa.CheckConstraint(
            "finalization_state IN ('partial', 'live_final', 'durable_final')",
            name="ck_utterances_finalization_state",
        ),
        sa.CheckConstraint("projection_version >= 1", name="ck_utterances_projection_version"),
        sa.CheckConstraint("revision >= 1", name="ck_utterances_revision"),
        sa.ForeignKeyConstraint(["segment_id"], ["recording_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_epoch_id"], ["source_epochs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_epoch_id", "utterance_id", name="uq_epoch_utterance"),
    )
    op.create_index("ix_utterances_segment_id", "utterances", ["segment_id"])
    op.create_index("ix_utterances_session_id", "utterances", ["session_id"])
    op.create_index("ix_utterances_source_epoch_id", "utterances", ["source_epoch_id"])
    op.create_table(
        "activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("activity_key_digest", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("started_offset_us", sa.Integer(), nullable=False),
        sa.Column("ended_offset_us", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.String(length=128), nullable=False),
        sa.Column("presentation_state", sa.String(length=32), nullable=False),
        sa.Column("recording_state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_activities_confidence"
        ),
        sa.CheckConstraint(
            "presentation_state IN ('unknown', 'active', 'stopped')",
            name="ck_activities_presentation_state",
        ),
        sa.CheckConstraint(
            "recording_state IN ('unknown', 'active', 'stopped')",
            name="ck_activities_recording_state",
        ),
        sa.CheckConstraint(
            "started_offset_us >= 0 AND (ended_offset_us IS NULL OR "
            "ended_offset_us >= started_offset_us)",
            name="ck_activities_offsets",
        ),
        sa.CheckConstraint(
            "state IN ('detected', 'running', 'ended')", name="ck_activities_state"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activities_activity_key_digest", "activities", ["activity_key_digest"])
    op.create_index("ix_activities_session_id", "activities", ["session_id"])
    op.create_index("ix_activities_state", "activities", ["state"])
    op.create_table(
        "activity_source_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("first_observed_offset_us", sa.Integer(), nullable=False),
        sa.Column("last_observed_offset_us", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["capture_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "source_id", name="uq_activity_source_link"),
    )
    op.create_index(
        "ix_activity_source_links_activity_id", "activity_source_links", ["activity_id"]
    )
    op.create_index(
        "ix_activity_source_links_source_id", "activity_source_links", ["source_id"]
    )
    op.create_table(
        "activity_participants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("identity_digest", sa.String(length=64), nullable=False),
        sa.Column("display_label", sa.String(length=512), nullable=True),
        sa.Column("is_self", sa.Boolean(), nullable=False),
        sa.Column("presence_state", sa.String(length=32), nullable=False),
        sa.Column("muted", sa.Boolean(), nullable=True),
        sa.Column("hand_raised", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.String(length=128), nullable=False),
        sa.Column("last_observed_offset_us", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_activity_participants_confidence",
        ),
        sa.CheckConstraint(
            "last_observed_offset_us >= 0", name="ck_activity_participants_offset"
        ),
        sa.CheckConstraint(
            "presence_state IN ('present', 'left', 'unknown')",
            name="ck_activity_participants_presence",
        ),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "activity_id", "identity_digest", name="uq_activity_participant_identity"
        ),
    )
    op.create_index(
        "ix_activity_participants_activity_id", "activity_participants", ["activity_id"]
    )
    op.create_index(
        "ix_activity_participants_identity_digest",
        "activity_participants",
        ["identity_digest"],
    )
    op.create_table(
        "speaker_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_speaker_profiles_display_name", "speaker_profiles", ["display_name"])
    op.create_table(
        "speaker_profile_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["speaker_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "normalized_alias", name="uq_speaker_profile_alias"),
    )
    op.create_index(
        "ix_speaker_profile_aliases_profile_id", "speaker_profile_aliases", ["profile_id"]
    )
    op.create_table(
        "speaker_prototypes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=256), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("speech_duration_ms", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("consent_provenance", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dimensions > 0", name="ck_speaker_prototypes_dimensions"),
        sa.CheckConstraint(
            "quality >= 0 AND quality <= 1", name="ck_speaker_prototypes_quality"
        ),
        sa.CheckConstraint(
            "speech_duration_ms > 0", name="ck_speaker_prototypes_duration"
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["speaker_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_speaker_prototypes_model_id", "speaker_prototypes", ["model_id"])
    op.create_index(
        "ix_speaker_prototypes_profile_id", "speaker_prototypes", ["profile_id"]
    )
    op.create_table(
        "speaker_semantic_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("identity_kind", sa.String(length=64), nullable=False),
        sa.Column("identity_digest", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_speaker_semantic_identities_confidence",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["speaker_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "identity_kind", "identity_digest", name="uq_speaker_semantic_identity"
        ),
    )
    op.create_index(
        "ix_speaker_semantic_identities_identity_digest",
        "speaker_semantic_identities",
        ["identity_digest"],
    )
    op.create_index(
        "ix_speaker_semantic_identities_profile_id",
        "speaker_semantic_identities",
        ["profile_id"],
    )
    op.create_table(
        "utterance_speaker_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("utterance_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("speaker_role", sa.String(length=32), nullable=False),
        sa.Column("display_label", sa.String(length=512), nullable=True),
        sa.Column("speaker_profile_id", sa.String(length=36), nullable=True),
        sa.Column("anonymous_track_id", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(length=128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_speaker_assignments_confidence",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_speaker_assignments_revision"),
        sa.CheckConstraint(
            "speaker_role IN ('self', 'remote', 'unknown')",
            name="ck_speaker_assignments_role",
        ),
        sa.ForeignKeyConstraint(["utterance_id"], ["utterances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["speaker_profile_id"], ["speaker_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_utterance_speaker_assignments_speaker_role",
        "utterance_speaker_assignments",
        ["speaker_role"],
    )
    op.create_index(
        "ix_utterance_speaker_assignments_speaker_profile_id",
        "utterance_speaker_assignments",
        ["speaker_profile_id"],
    )
    op.create_index(
        "ix_utterance_speaker_assignments_utterance_id",
        "utterance_speaker_assignments",
        ["utterance_id"],
        unique=True,
    )
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_message_sequence"),
    )
    op.create_index("ix_agent_messages_run_id", "agent_messages", ["run_id"])

    now = datetime.now(UTC)
    buttons = sa.table(
        "button_definitions",
        *(
            sa.column(name)
            for name in (
                "id",
                "key",
                "enabled",
                "label",
                "prompt_template",
                "context_strategy",
                "context_value",
                "hard_character_cap",
                "definition_version",
            )
        ),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    presets = sa.table(
        "action_presets",
        sa.column("id"),
        sa.column("name"),
        sa.column("is_default"),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    items = sa.table(
        "action_preset_items",
        sa.column("preset_id"),
        sa.column("button_id"),
        sa.column("position"),
    )

    action_ids = {
        definition["key"]: _factory_id("action", definition["key"])
        for definition in BUILTIN_ACTIONS
    }
    bind.execute(
        sa.insert(buttons),
        [
            {
                "id": action_ids[definition["key"]],
                "enabled": True,
                "definition_version": 1,
                "created_at": now,
                "updated_at": now,
                **definition,
            }
            for definition in BUILTIN_ACTIONS
        ],
    )

    preset_ids = {
        definition["name"]: _factory_id("preset", definition["name"])
        for definition in BUILTIN_PRESETS
    }
    bind.execute(
        sa.insert(presets),
        [
            {
                "id": preset_ids[definition["name"]],
                "name": definition["name"],
                "is_default": definition["name"] == "Default",
                "created_at": now,
                "updated_at": now,
            }
            for definition in BUILTIN_PRESETS
        ],
    )
    bind.execute(
        sa.insert(items),
        [
            {
                "preset_id": preset_ids[definition["name"]],
                "button_id": action_ids[action_key],
                "position": position,
            }
            for definition in BUILTIN_PRESETS
            for position, action_key in enumerate(definition["action_keys"])
        ],
    )


def downgrade() -> None:
    for table_name in (
        "agent_messages",
        "utterance_speaker_assignments",
        "speaker_semantic_identities",
        "speaker_prototypes",
        "speaker_profile_aliases",
        "speaker_profiles",
        "activity_participants",
        "activity_source_links",
        "activities",
        "utterances",
        "source_epochs",
        "evidence_event_counters",
        "evidence_event_diagnostics",
        "evidence_event_tombstones",
        "agent_runs",
        "session_source_bindings",
        "recording_segments",
        "agent_threads",
        "sessions",
        "action_preset_items",
        "maintenance_state",
        "ui_events",
        "capture_sources",
        "pairing_requests",
        "paired_clients",
        "button_definitions",
        "action_presets",
    ):
        op.drop_table(table_name)
