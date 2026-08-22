import json
import logging

import pytest
from elsewise.observability import RuntimeDiagnostics, log_event


def test_structured_events_are_json_and_reject_content_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="elsewise.events")
    log_event(
        "agent.completed",
        session_id="session-safe-id",
        run_id="run-safe-id",
        state="completed",
        queue_size=0,
    )

    payload = json.loads(caplog.records[-1].message)
    assert payload == {
        "event": "agent.completed",
        "queue_size": 0,
        "run_id": "run-safe-id",
        "session_id": "session-safe-id",
        "state": "completed",
    }
    with pytest.raises(ValueError, match="Unsafe structured log field"):
        log_event("unsafe", transcript="private caption")
    assert "private caption" not in caplog.text


def test_runtime_diagnostics_count_connections_without_content() -> None:
    counters = RuntimeDiagnostics()
    counters.connected("ingest")
    counters.connected("ingest")
    counters.disconnected("ingest")

    assert counters.snapshot() == {
        "ingest_connections_total": 2,
        "ingest_clients_connected": 1,
        "ingest_disconnects_total": 1,
        "ui_connections_total": 0,
        "ui_clients_connected": 0,
        "ui_disconnects_total": 0,
        "launcher_connections_total": 0,
        "launcher_clients_connected": 0,
        "launcher_disconnects_total": 0,
    }
