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
        sa.Column("paired_client_id", sa.String(length=36), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("driver_id", sa.String(length=128), nullable=False),
        sa.Column("driver_version", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("tab_instance_id", sa.String(length=128), nullable=False),
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
        sa.CheckConstraint("protocol_version = 2", name="ck_capture_sources_protocol"),
        sa.ForeignKeyConstraint(["paired_client_id"], ["paired_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capture_sources_paired_client_id", "capture_sources", ["paired_client_id"])
    op.create_index("ix_capture_sources_tab_instance_id", "capture_sources", ["tab_instance_id"])
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
        sa.Column("agent_status", sa.String(length=32), nullable=False),
        sa.Column("requested_agent_cwd", sa.Text(), nullable=True),
        sa.Column("resolved_agent_cwd", sa.Text(), nullable=True),
        sa.Column("agent_cwd_fallback", sa.Boolean(), nullable=False),
        sa.Column("allow_workspace_write", sa.Boolean(), nullable=False),
        sa.Column("allow_network", sa.Boolean(), nullable=False),
        sa.Column("permissions_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permission_audit", sa.JSON(), nullable=False),
        sa.Column("selected_source_id", sa.String(length=36), nullable=True),
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
        sa.ForeignKeyConstraint(["action_preset_id"], ["action_presets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["selected_source_id"], ["capture_sources.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_action_preset_id", "sessions", ["action_preset_id"])
    op.create_index("ix_sessions_agent_provider", "sessions", ["agent_provider"])
    op.create_index("ix_sessions_recording_status", "sessions", ["recording_status"])
    op.create_index("ix_sessions_selected_source_id", "sessions", ["selected_source_id"])
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
        "source_epochs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("segment_id", sa.String(length=36), nullable=True),
        sa.Column("producer_epoch_id", sa.String(length=128), nullable=False),
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
        sa.CheckConstraint(
            "reconnect_count >= 0 AND producer_restart_count >= 0 "
            "AND transport_error_count >= 0 AND dropped_event_count >= 0 "
            "AND received_event_count >= 0 AND rejected_event_count >= 0",
            name="ck_source_epochs_counters",
        ),
        sa.CheckConstraint(
            "state IN ('starting', 'running', 'stopping', 'stopped', 'failed')",
            name="ck_source_epochs_state",
        ),
        sa.ForeignKeyConstraint(["segment_id"], ["recording_segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["capture_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_epochs_segment_id", "source_epochs", ["segment_id"])
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
        "caption_event_tombstones",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_caption_event_tombstones_received_at",
        "caption_event_tombstones",
        ["received_at"],
    )
    op.create_table(
        "caption_event_diagnostics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_caption_event_diagnostics_reason_code",
        "caption_event_diagnostics",
        ["reason_code"],
    )
    op.create_index(
        "ix_caption_event_diagnostics_received_at",
        "caption_event_diagnostics",
        ["received_at"],
    )
    op.create_index(
        "ix_caption_event_diagnostics_source_id",
        "caption_event_diagnostics",
        ["source_id"],
    )
    op.create_table(
        "caption_event_counters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("processing_result", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_type",
            "processing_result",
            "reason_code",
            "protocol_version",
            name="uq_caption_event_counter",
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
        sa.Column("speaker", sa.String(length=512), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("final", sa.Boolean(), nullable=False),
        sa.Column("origin_kind", sa.String(length=64), nullable=False),
        sa.Column("origin_confidence", sa.Float(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("first_session_offset_us", sa.Integer(), nullable=False),
        sa.Column("last_session_offset_us", sa.Integer(), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_client_seq", sa.Integer(), nullable=False),
        sa.Column("last_client_seq", sa.Integer(), nullable=False),
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
        "utterances",
        "source_epochs",
        "caption_event_counters",
        "caption_event_diagnostics",
        "caption_event_tombstones",
        "agent_runs",
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
