from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptionEventCounterRecord,
    CaptionEventDiagnosticRecord,
    CaptionEventTombstoneRecord,
    CaptureSourceRecord,
    MaintenanceStateRecord,
    UiEventRecord,
)
from elsewise.services import maintenance
from sqlalchemy import func, inspect, select

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def test_startup_retention_is_bounded_private_and_vacuum_is_throttled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database.from_path(tmp_path / "maintenance.sqlite3")
    database.migrate()
    monkeypatch.setattr(maintenance, "MAX_DIAGNOSTICS", 2)
    monkeypatch.setattr(maintenance, "MAX_TOMBSTONES", 3)
    monkeypatch.setattr(maintenance, "MAX_UI_EVENTS", 2)
    vacuum_calls = 0

    def vacuum() -> None:
        nonlocal vacuum_calls
        vacuum_calls += 1

    monkeypatch.setattr(database, "vacuum", vacuum)
    with database.transaction() as db:
        for index, (reason, age) in enumerate(
            (
                ("no_running_session", timedelta(hours=25)),
                ("source_not_bound", timedelta(days=8)),
                ("source_not_bound", timedelta(hours=3)),
                ("source_not_bound", timedelta(hours=2)),
                ("source_not_bound", timedelta(hours=1)),
            )
        ):
            db.add(
                CaptionEventDiagnosticRecord(
                    event_id=f"diagnostic-{index}",
                    source_id="source",
                    event_type="utterance.upsert",
                    processing_result="rejected",
                    reason_code=reason,
                    protocol_version=1,
                    received_at=NOW - age,
                )
            )
        for index in range(6):
            db.add(
                CaptionEventTombstoneRecord(
                    event_id=f"tombstone-{index}",
                    processing_result="applied",
                    received_at=NOW - timedelta(hours=index),
                )
            )
            db.add(
                UiEventRecord(
                    event_type="test.event",
                    aggregate_id=str(index),
                    payload={"value": index},
                    created_at=NOW - timedelta(minutes=index),
                )
            )
        db.add(
            CaptionEventCounterRecord(
                event_type="utterance.upsert",
                processing_result="rejected",
                reason_code="no_running_session",
                protocol_version=1,
                count=99,
                first_received_at=NOW - timedelta(days=30),
                last_received_at=NOW,
            )
        )
        db.add_all(
            [
                CaptureSourceRecord(
                    source_id="old-source",
                    installation_id="installation",
                    platform="google_meet",
                    enabled=False,
                    connected=False,
                    updated_at=NOW - timedelta(days=8),
                ),
                CaptureSourceRecord(
                    source_id="recent-source",
                    installation_id="installation",
                    platform="google_meet",
                    enabled=False,
                    connected=False,
                    updated_at=NOW - timedelta(days=1),
                ),
            ]
        )

    result = maintenance.perform_startup_maintenance(database, now=NOW)
    assert result.vacuumed is True
    assert vacuum_calls == 1
    with database.transaction() as db:
        assert db.scalar(select(func.count(CaptionEventDiagnosticRecord.id))) == 2
        assert db.scalar(select(func.count(CaptionEventTombstoneRecord.event_id))) == 3
        assert db.scalar(select(func.count(UiEventRecord.id))) == 2
        assert db.get(CaptureSourceRecord, "old-source") is None
        assert db.get(CaptureSourceRecord, "recent-source") is not None
        assert db.scalar(select(CaptionEventCounterRecord.count)) == 99
        state = db.get(MaintenanceStateRecord, 1)
        assert state is not None
        assert state.ui_events_pruned_through == 4

    diagnostic_columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("caption_event_diagnostics")
    }
    assert {"text", "speaker", "meeting_title"}.isdisjoint(diagnostic_columns)

    with database.transaction() as db:
        db.add(
            CaptionEventTombstoneRecord(
                event_id="expired-after-first-run",
                processing_result="applied",
                received_at=NOW - timedelta(days=8),
            )
        )
    second = maintenance.perform_startup_maintenance(database, now=NOW + timedelta(days=1))
    assert second.vacuumed is False
    assert vacuum_calls == 1
    database.dispose()
