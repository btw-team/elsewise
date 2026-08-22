from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptionEventDiagnosticRecord,
    CaptionEventTombstoneRecord,
    CaptureSourceRecord,
    MaintenanceStateRecord,
    RecordingSegmentRecord,
    SessionRecord,
    UiEventRecord,
    UtteranceRecord,
)

DIAGNOSTIC_RETENTION = timedelta(days=7)
NO_RUNNING_SESSION_RETENTION = timedelta(hours=24)
TOMBSTONE_RETENTION = timedelta(days=7)
SOURCE_RETENTION = timedelta(days=7)
VACUUM_INTERVAL = timedelta(days=7)
MAX_DIAGNOSTICS = 20_000
MAX_TOMBSTONES = 50_000
MAX_UI_EVENTS = 10_000


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    diagnostics_deleted: int = 0
    tombstones_deleted: int = 0
    sources_deleted: int = 0
    ui_events_deleted: int = 0
    pruned_through: int = 0
    vacuumed: bool = False


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _trim_to_limit(database_session: object, model: type[object], limit: int) -> int:
    id_column = getattr(model, "id", None)
    if id_column is None:
        return 0
    threshold = database_session.scalar(  # type: ignore[attr-defined]
        select(id_column).order_by(id_column.desc()).offset(limit - 1).limit(1)
    )
    if threshold is None:
        return 0
    result = database_session.execute(delete(model).where(id_column < threshold))  # type: ignore[attr-defined]
    return int(getattr(result, "rowcount", 0) or 0)


def _trim_tombstones(database_session: object, limit: int) -> int:
    count = database_session.scalar(  # type: ignore[attr-defined]
        select(func.count(CaptionEventTombstoneRecord.event_id))
    )
    excess = int(count or 0) - limit
    if excess <= 0:
        return 0
    result = database_session.execute(  # type: ignore[attr-defined]
        delete(CaptionEventTombstoneRecord).where(
            CaptionEventTombstoneRecord.event_id.in_(
                select(CaptionEventTombstoneRecord.event_id)
                .order_by(
                    CaptionEventTombstoneRecord.received_at,
                    CaptionEventTombstoneRecord.event_id,
                )
                .limit(excess)
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def perform_startup_maintenance(
    database: Database, *, now: datetime | None = None
) -> MaintenanceResult:
    current = now or datetime.now(UTC)
    diagnostics_deleted = 0
    tombstones_deleted = 0
    sources_deleted = 0
    ui_events_deleted = 0
    pruned_through = 0
    vacuum_due = False

    with database.transaction() as db:
        state = db.get(MaintenanceStateRecord, 1)
        if state is None:
            state = MaintenanceStateRecord(id=1)
            db.add(state)
            db.flush()

        diagnostic_result = db.execute(
            delete(CaptionEventDiagnosticRecord).where(
                or_(
                    (CaptionEventDiagnosticRecord.reason_code == "no_running_session")
                    & (
                        CaptionEventDiagnosticRecord.received_at
                        < current - NO_RUNNING_SESSION_RETENTION
                    ),
                    (CaptionEventDiagnosticRecord.reason_code != "no_running_session")
                    & (CaptionEventDiagnosticRecord.received_at < current - DIAGNOSTIC_RETENTION),
                )
            )
        )
        diagnostics_deleted += int(getattr(diagnostic_result, "rowcount", 0) or 0)
        diagnostics_deleted += _trim_to_limit(db, CaptionEventDiagnosticRecord, MAX_DIAGNOSTICS)

        tombstone_result = db.execute(
            delete(CaptionEventTombstoneRecord).where(
                CaptionEventTombstoneRecord.received_at < current - TOMBSTONE_RETENTION
            )
        )
        tombstones_deleted += int(getattr(tombstone_result, "rowcount", 0) or 0)
        tombstones_deleted += _trim_tombstones(db, MAX_TOMBSTONES)

        referenced_sources = {
            value
            for row in db.execute(
                select(
                    SessionRecord.enabled_source_id,
                    SessionRecord.active_source_id,
                    SessionRecord.finalize_grace_source_id,
                )
            )
            for value in row
            if value
        }
        referenced_sources.update(
            value
            for value in db.scalars(
                select(RecordingSegmentRecord.source_id).where(
                    RecordingSegmentRecord.source_id.is_not(None)
                )
            )
            if value
        )
        referenced_sources.update(db.scalars(select(UtteranceRecord.source_id)))
        source_statement = delete(CaptureSourceRecord).where(
            CaptureSourceRecord.enabled.is_(False),
            CaptureSourceRecord.connected.is_(False),
            CaptureSourceRecord.updated_at < current - SOURCE_RETENTION,
        )
        if referenced_sources:
            source_statement = source_statement.where(
                CaptureSourceRecord.source_id.not_in(referenced_sources)
            )
        source_result = db.execute(source_statement)
        sources_deleted = int(getattr(source_result, "rowcount", 0) or 0)

        keep_from = db.scalar(
            select(UiEventRecord.id)
            .order_by(UiEventRecord.id.desc())
            .offset(MAX_UI_EVENTS - 1)
            .limit(1)
        )
        if keep_from is not None:
            deleted_max = db.scalar(
                select(func.max(UiEventRecord.id)).where(UiEventRecord.id < keep_from)
            )
            if deleted_max is not None:
                event_result = db.execute(delete(UiEventRecord).where(UiEventRecord.id < keep_from))
                ui_events_deleted = int(getattr(event_result, "rowcount", 0) or 0)
                state.ui_events_pruned_through = max(
                    state.ui_events_pruned_through, int(deleted_max)
                )
        pruned_through = state.ui_events_pruned_through
        cleaned = bool(
            diagnostics_deleted or tombstones_deleted or sources_deleted or ui_events_deleted
        )
        vacuum_due = cleaned and (
            state.last_vacuum_at is None or current - _utc(state.last_vacuum_at) >= VACUUM_INTERVAL
        )

    vacuumed = False
    if vacuum_due:
        try:
            database.vacuum()
        except Exception as exc:
            log_event("database.vacuum_failed", reason=type(exc).__name__)
        else:
            vacuumed = True
            with database.transaction() as db:
                state = db.get(MaintenanceStateRecord, 1)
                assert state is not None
                state.last_vacuum_at = current

    result = MaintenanceResult(
        diagnostics_deleted=diagnostics_deleted,
        tombstones_deleted=tombstones_deleted,
        sources_deleted=sources_deleted,
        ui_events_deleted=ui_events_deleted,
        pruned_through=pruned_through,
        vacuumed=vacuumed,
    )
    log_event(
        "database.maintenance",
        result=(
            f"diagnostics={diagnostics_deleted},tombstones={tombstones_deleted},"
            f"sources={sources_deleted},ui_events={ui_events_deleted},vacuumed={vacuumed}"
        ),
    )
    return result


def mark_sources_disconnected(database: Database) -> None:
    with database.transaction() as db:
        db.execute(update(CaptureSourceRecord).values(connected=False, enabled=False))
