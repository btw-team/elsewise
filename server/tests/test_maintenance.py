from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    CaptureSourceRecord,
    EvidenceEventCounterRecord,
    EvidenceEventDiagnosticRecord,
    EvidenceEventTombstoneRecord,
    MaintenanceStateRecord,
    PairedClientRecord,
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
                ("no_active_session", timedelta(hours=25)),
                ("source_not_bound", timedelta(days=8)),
                ("source_not_bound", timedelta(hours=3)),
                ("source_not_bound", timedelta(hours=2)),
                ("source_not_bound", timedelta(hours=1)),
            )
        ):
            db.add(
                EvidenceEventDiagnosticRecord(
                    event_id=f"diagnostic-{index}",
                    source_id="source",
                    capability="captions",
                    event_kind="caption.partial",
                    processing_result="rejected",
                    reason_code=reason,
                    protocol_version=3,
                    received_at=NOW - age,
                )
            )
        for index in range(6):
            db.add(
                EvidenceEventTombstoneRecord(
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
            EvidenceEventCounterRecord(
                capability="captions",
                event_kind="caption.partial",
                processing_result="rejected",
                reason_code="no_active_session",
                protocol_version=3,
                count=99,
                first_received_at=NOW - timedelta(days=30),
                last_received_at=NOW,
            )
        )
        client = PairedClientRecord(
            installation_id="00000000-0000-4000-8000-000000000001",
            browser_family="chrome",
            display_name="Test Chrome",
            credential_digest="0" * 64,
        )
        db.add(client)
        db.flush()
        db.add_all(
            [
                CaptureSourceRecord(
                    id="old-source",
                    paired_client_id=client.id,
                    platform="google_meet",
                    driver_id="browser_semantic",
                    driver_version="3.0.0",
                    tab_instance_id="old-tab",
                    available=False,
                    connected=False,
                    updated_at=NOW - timedelta(days=8),
                ),
                CaptureSourceRecord(
                    id="recent-source",
                    paired_client_id=client.id,
                    platform="google_meet",
                    driver_id="browser_semantic",
                    driver_version="3.0.0",
                    tab_instance_id="recent-tab",
                    available=False,
                    connected=False,
                    updated_at=NOW - timedelta(days=1),
                ),
            ]
        )

    result = maintenance.perform_startup_maintenance(database, now=NOW)
    assert result.vacuumed is True
    assert vacuum_calls == 1
    with database.transaction() as db:
        assert db.scalar(select(func.count(EvidenceEventDiagnosticRecord.id))) == 2
        assert db.scalar(select(func.count(EvidenceEventTombstoneRecord.event_id))) == 3
        assert db.scalar(select(func.count(UiEventRecord.id))) == 2
        assert db.get(CaptureSourceRecord, "old-source") is None
        assert db.get(CaptureSourceRecord, "recent-source") is not None
        assert db.scalar(select(EvidenceEventCounterRecord.count)) == 99
        state = db.get(MaintenanceStateRecord, 1)
        assert state is not None
        assert state.ui_events_pruned_through == 4

    diagnostic_columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("evidence_event_diagnostics")
    }
    assert {"text", "speaker", "meeting_title"}.isdisjoint(diagnostic_columns)

    with database.transaction() as db:
        db.add(
            EvidenceEventTombstoneRecord(
                event_id="expired-after-first-run",
                processing_result="applied",
                received_at=NOW - timedelta(days=8),
            )
        )
    second = maintenance.perform_startup_maintenance(database, now=NOW + timedelta(days=1))
    assert second.vacuumed is False
    assert vacuum_calls == 1
    database.dispose()
