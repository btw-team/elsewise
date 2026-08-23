from datetime import UTC, datetime

import pytest
from elsewise.domain.session import SessionMachine, TransitionRejected
from elsewise.domain.states import AgentStatus, CaptureStatus, RecordingStatus

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_start_without_source_waits_and_enqueues_initial_turn_once() -> None:
    session = SessionMachine()
    result = session.start(now=NOW)
    assert result.segment_sequence == 1
    assert result.enqueue_initial_turn is True
    assert session.recording_status is RecordingStatus.RUNNING
    assert session.capture_status is CaptureStatus.WAITING_FOR_SOURCE
    assert session.agent_status is AgentStatus.STARTING


def test_source_binds_after_start_and_switch_is_rejected() -> None:
    session = SessionMachine()
    session.start(now=NOW)
    session.enable_source("meet-document")
    assert session.active_source_id == "meet-document"
    assert session.capture_status is CaptureStatus.CAPTIONS_NOT_DETECTED
    with pytest.raises(TransitionRejected, match="source_switch_rejected"):
        session.enable_source("teams-document")


def test_stop_and_restart_create_segment_without_repeating_initial_turn() -> None:
    session = SessionMachine()
    session.enable_source("meet-document")
    first = session.start(now=NOW)
    session.stop(now=NOW)
    second = session.start(now=NOW)
    assert first.segment_sequence == 1
    assert first.enqueue_initial_turn is True
    assert second.segment_sequence == 2
    assert second.enqueue_initial_turn is False
    assert session.active_source_id == "meet-document"


def test_start_and_stop_conflicts_are_typed() -> None:
    session = SessionMachine()
    with pytest.raises(TransitionRejected, match="not_running"):
        session.stop(now=NOW)
    session.start(now=NOW)
    with pytest.raises(TransitionRejected, match="already_running"):
        session.start(now=NOW)
