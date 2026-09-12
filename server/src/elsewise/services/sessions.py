from datetime import UTC, datetime
from pathlib import Path
from time import monotonic_ns
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    ActionPresetRecord,
    AgentThreadRecord,
    RecordingSegmentRecord,
    SessionRecord,
    SourceEpochRecord,
    UtteranceRecord,
    utc_now,
)
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event


def session_payload(record: SessionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "description": record.description,
        "language": record.language,
        "initial_prompt": record.initial_prompt,
        "action_preset_id": record.action_preset_id,
        "agent_provider": record.agent_provider,
        "agent_model": record.agent_model,
        "agent_reasoning_effort": record.agent_reasoning_effort,
        "recording_status": record.recording_status,
        "source_status": record.source_status,
        "agent_status": record.agent_status,
        "selected_source_id": record.selected_source_id,
        "allow_workspace_write": record.allow_workspace_write,
        "allow_network": record.allow_network,
        "requested_agent_cwd": record.requested_agent_cwd,
        "resolved_agent_cwd": record.resolved_agent_cwd,
        "agent_cwd_fallback": record.agent_cwd_fallback,
        "permissions_updated_at": record.permissions_updated_at.isoformat()
        if record.permissions_updated_at
        else None,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "stopped_at": record.stopped_at.isoformat() if record.stopped_at else None,
        "version": record.version,
    }


def prepare_agent_cwd(requested: str | None, *, create_missing: bool) -> str | None:
    if requested is None or not requested.strip():
        return None
    candidate = Path(requested.strip()).expanduser()
    try:
        if not candidate.exists():
            if not create_missing:
                raise ServiceError(
                    "agent_cwd_missing",
                    "The selected agent working directory does not exist.",
                    status_code=409,
                )
            candidate.mkdir(parents=True, exist_ok=True)
        resolved = candidate.resolve(strict=True)
    except ServiceError:
        raise
    except OSError as exc:
        raise ServiceError(
            "agent_cwd_unavailable",
            f"Unable to use the selected agent working directory: {exc}",
            status_code=422,
        ) from exc
    if not resolved.is_dir():
        raise ServiceError(
            "agent_cwd_not_directory",
            "The selected agent working directory is not a directory.",
            status_code=422,
        )
    return str(resolved)


class SessionService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        title: str,
        description: str = "",
        language: str = "ru",
        initial_prompt: str = "",
        action_preset_id: str | None = None,
        agent_provider: str = "codex",
        agent_model: str | None = None,
        agent_reasoning_effort: str | None = None,
        requested_agent_cwd: str | None = None,
        allow_workspace_write: bool = False,
        allow_network: bool = False,
    ) -> SessionRecord:
        with self.database.transaction() as db:
            resolved_action_preset_id = self._resolve_action_preset_id(db, action_preset_id)
            record = SessionRecord(
                title=title,
                description=description,
                language=language,
                initial_prompt=initial_prompt,
                action_preset_id=resolved_action_preset_id,
                agent_provider=agent_provider,
                agent_model=agent_model,
                agent_reasoning_effort=agent_reasoning_effort,
                requested_agent_cwd=requested_agent_cwd,
                allow_workspace_write=allow_workspace_write,
                allow_network=allow_network,
            )
            db.add(record)
            db.flush()
            emit_ui_event(db, "session.state", record.id, session_payload(record))
            log_event("session.created", session_id=record.id, state=record.recording_status)
            return record

    def list_all(self) -> list[SessionRecord]:
        with self.database.transaction() as db:
            return list(db.scalars(select(SessionRecord).order_by(SessionRecord.created_at.desc())))

    def get(self, session_id: str) -> SessionRecord:
        with self.database.transaction() as db:
            return self._get(db, session_id)

    def update(
        self,
        session_id: str,
        changes: dict[str, Any],
        *,
        create_agent_cwd: bool = False,
    ) -> SessionRecord:
        with self.database.transition_lock, self.database.transaction() as db:
            record = self._get(db, session_id)
            normalized_changes = dict(changes)
            if "agent_provider" in normalized_changes:
                existing_thread = db.scalar(
                    select(AgentThreadRecord.id).where(AgentThreadRecord.session_id == session_id)
                )
                provider_changed = normalized_changes["agent_provider"] != record.agent_provider
                if existing_thread is not None and provider_changed:
                    raise ServiceError(
                        "agent_provider_locked",
                        "The agent provider cannot be changed after the agent thread is created.",
                        status_code=409,
                    )
            post_start_editable = {
                "title",
                "description",
                "agent_model",
                "agent_reasoning_effort",
                "allow_workspace_write",
                "allow_network",
            }
            if changes and record.recording_status in {"starting", "running", "stopping"}:
                raise ServiceError(
                    "session_running",
                    "Stop the session before changing its settings.",
                    status_code=409,
                )
            if (
                changes
                and record.started_at is not None
                and not set(normalized_changes).issubset(post_start_editable)
            ):
                raise ServiceError(
                    "session_already_started",
                    "These session settings are locked after the first start.",
                    status_code=409,
                )
            if "requested_agent_cwd" in normalized_changes:
                normalized_changes["requested_agent_cwd"] = prepare_agent_cwd(
                    normalized_changes["requested_agent_cwd"],
                    create_missing=create_agent_cwd,
                )
            if "action_preset_id" in normalized_changes:
                normalized_changes["action_preset_id"] = self._resolve_action_preset_id(
                    db, normalized_changes["action_preset_id"]
                )
            permission_keys = {"allow_workspace_write", "allow_network"}
            if permission_keys.intersection(normalized_changes):
                changed = {
                    key: value
                    for key, value in normalized_changes.items()
                    if key in permission_keys and getattr(record, key) != value
                }
                if changed:
                    now = utc_now()
                    record.permissions_updated_at = now
                    audit = dict(record.permission_audit)
                    entries = list(audit.get("entries", []))
                    entries.append({"at": now.isoformat(), "changes": changed})
                    audit["entries"] = entries[-100:]
                    record.permission_audit = audit
            for key, value in normalized_changes.items():
                setattr(record, key, value)
            record.version += 1
            db.flush()
            emit_ui_event(db, "session.state", record.id, session_payload(record))
            return record

    @staticmethod
    def _resolve_action_preset_id(db: Session, preset_id: str | None) -> str | None:
        if preset_id is None:
            return db.scalar(
                select(ActionPresetRecord.id).where(ActionPresetRecord.is_default.is_(True))
            )
        if db.get(ActionPresetRecord, preset_id) is None:
            raise ServiceError(
                "action_preset_not_found",
                "Action preset not found.",
                status_code=404,
            )
        return preset_id

    def start(self, session_id: str, *, now: datetime | None = None) -> SessionRecord:
        started_at = now or utc_now()
        with self.database.transition_lock:
            try:
                with self.database.transaction() as db:
                    record = self._get(db, session_id)
                    if record.recording_status == "running":
                        return record
                    if record.recording_status == "stopping":
                        raise ServiceError(
                            "session_transition_in_progress",
                            "The session is still stopping.",
                            status_code=409,
                        )
                    other = db.scalar(
                        select(SessionRecord.id).where(
                            SessionRecord.recording_status.in_(("starting", "running", "stopping")),
                            SessionRecord.id != session_id,
                        )
                    )
                    if other is not None:
                        raise ServiceError(
                            "another_session_running",
                            "Only one session can record at a time.",
                        )
                    next_sequence = (
                        db.scalar(
                            select(func.max(RecordingSegmentRecord.sequence)).where(
                                RecordingSegmentRecord.session_id == session_id
                            )
                        )
                        or 0
                    ) + 1
                    record.recording_status = "starting"
                    record.started_at = started_at
                    record.stopped_at = None
                    record.stop_requested_at = None
                    record.stop_boundary_offset_us = None
                    record.monotonic_origin_ns = monotonic_ns()
                    record.selected_source_id = None
                    record.source_status = "waiting_for_source"
                    record.version += 1
                    segment = RecordingSegmentRecord(
                        session_id=record.id,
                        sequence=next_sequence,
                        started_at=started_at,
                    )
                    db.add(segment)
                    db.flush()
                    record.recording_status = "running"
                    emit_ui_event(db, "session.state", record.id, session_payload(record))
                    log_event("session.started", session_id=record.id, state="running")
                    return record
            except IntegrityError as exc:
                raise ServiceError(
                    "another_session_running", "Only one session can record at a time."
                ) from exc

    def begin_stop(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> SessionRecord:
        requested_at = now or utc_now()
        with self.database.transition_lock, self.database.transaction() as db:
            record = self._get(db, session_id)
            if record.recording_status == "stopped":
                return record
            if record.recording_status == "stopping":
                return record
            if record.recording_status != "running":
                raise ServiceError("session_not_running", "The session is not running.")
            record.recording_status = "stopping"
            record.stop_requested_at = requested_at
            record.stop_boundary_offset_us = max(
                0,
                (monotonic_ns() - (record.monotonic_origin_ns or monotonic_ns())) // 1_000,
            )
            record.version += 1
            emit_ui_event(db, "session.state", record.id, session_payload(record))
            return record

    def finish_stop(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
        reason: str = "user",
    ) -> SessionRecord:
        stopped_at = now or utc_now()
        with self.database.transition_lock, self.database.transaction() as db:
            record = self._get(db, session_id)
            if record.recording_status == "stopped":
                return record
            if record.recording_status != "stopping":
                raise ServiceError(
                    "session_not_stopping", "The session is not stopping.", status_code=409
                )
            segment = db.scalar(
                select(RecordingSegmentRecord)
                .where(
                    RecordingSegmentRecord.session_id == session_id,
                    RecordingSegmentRecord.stopped_at.is_(None),
                )
                .order_by(RecordingSegmentRecord.sequence.desc())
            )
            if segment is None:
                raise ServiceError(
                    "segment_missing", "The active recording segment is missing.", status_code=500
                )
            segment.stopped_at = stopped_at
            segment.stop_reason = reason
            record.recording_status = "stopped"
            record.stopped_at = stopped_at
            record.selected_source_id = None
            record.source_status = "no_source"
            record.version += 1
            for epoch in db.scalars(
                select(SourceEpochRecord).where(
                    SourceEpochRecord.session_id == session_id,
                    SourceEpochRecord.state.in_(("starting", "running", "stopping")),
                )
            ):
                epoch.state = "stopped"
                epoch.ended_at = stopped_at
                epoch.end_reason = epoch.end_reason or "forced_stop"
            for utterance in db.scalars(
                select(UtteranceRecord).where(
                    UtteranceRecord.session_id == session_id,
                    UtteranceRecord.final.is_(False),
                )
            ):
                utterance.final = True
            emit_ui_event(db, "session.state", record.id, session_payload(record))
            log_event("session.stopped", session_id=record.id, state="stopped", reason=reason)
            return record

    def stop(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
        reason: str = "user",
    ) -> SessionRecord:
        self.begin_stop(session_id, now=now)
        return self.finish_stop(session_id, now=now, reason=reason)

    def delete(self, session_id: str) -> None:
        with self.database.transaction() as db:
            record = self._get(db, session_id)
            if record.recording_status in {"starting", "running", "stopping"}:
                raise ServiceError("session_running", "Stop the session before deleting it.")
            db.delete(record)
            emit_ui_event(db, "session.state", session_id, {"id": session_id, "deleted": True})
            log_event("session.deleted", session_id=session_id, state="deleted")

    def utterances(self, session_id: str) -> list[UtteranceRecord]:
        with self.database.transaction() as db:
            self._get(db, session_id)
            return list(
                db.scalars(
                    select(UtteranceRecord)
                    .where(UtteranceRecord.session_id == session_id)
                    .order_by(
                        UtteranceRecord.first_session_offset_us,
                        UtteranceRecord.first_client_seq,
                    )
                )
            )

    def cleanup_partial_utterances(self, session_id: str) -> int:
        with self.database.transaction() as db:
            record = self._get(db, session_id)
            if record.recording_status in {"starting", "running", "stopping"}:
                return 0
            result = db.execute(
                delete(UtteranceRecord).where(
                    UtteranceRecord.session_id == session_id,
                    UtteranceRecord.final.is_(False),
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _get(db: Session, session_id: str) -> SessionRecord:
        record = db.get(SessionRecord, session_id)
        if record is None:
            raise ServiceError("session_not_found", "Session not found.", status_code=404)
        return record


def recover_after_restart(database: Database) -> None:
    recovered_at = datetime.now(UTC)
    with database.transaction() as db:
        running_sessions = db.scalars(
            select(SessionRecord).where(
                SessionRecord.recording_status.in_(("starting", "running", "stopping"))
            )
        )
        for record in running_sessions:
            record.recording_status = "stopped"
            record.source_status = "no_source"
            record.stopped_at = recovered_at
            record.selected_source_id = None
            record.version += 1
            open_segments = db.scalars(
                select(RecordingSegmentRecord).where(
                    RecordingSegmentRecord.session_id == record.id,
                    RecordingSegmentRecord.stopped_at.is_(None),
                )
            )
            for segment in open_segments:
                segment.stopped_at = recovered_at
                segment.stop_reason = "daemon_restart"
            for epoch in db.scalars(
                select(SourceEpochRecord).where(
                    SourceEpochRecord.session_id == record.id,
                    SourceEpochRecord.state.in_(("starting", "running", "stopping")),
                )
            ):
                epoch.state = "stopped"
                epoch.ended_at = recovered_at
                epoch.end_reason = "daemon_restart"
            db.execute(
                delete(UtteranceRecord).where(
                    UtteranceRecord.session_id == record.id,
                    UtteranceRecord.final.is_(False),
                )
            )
            emit_ui_event(db, "session.state", record.id, session_payload(record))
            log_event("session.recovered", session_id=record.id, state="stopped")

        from elsewise.persistence.models import AgentRunRecord

        interrupted_runs = db.scalars(
            select(AgentRunRecord).where(
                AgentRunRecord.status.in_(("queued", "starting", "streaming"))
            )
        )
        for run in interrupted_runs:
            run.status = "interrupted"
            run.completed_at = datetime.now(UTC)
            log_event("agent.recovered", run_id=run.id, state="interrupted")
            run.error_type = "daemon_restart"
            run.error_message = "The daemon restarted while the run was active."
            emit_ui_event(db, "agent.failed", run.id, {"status": "interrupted"})
