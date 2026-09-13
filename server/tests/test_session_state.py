from itertools import product

import pytest
from elsewise.domain.session import SessionMachine, TransitionRejected
from elsewise.domain.states import AgentStatus, RecordingStatus, SourceStatus
from elsewise.sources.contracts import SourceRole


def test_start_without_source_waits_and_enqueues_initial_turn_once() -> None:
    session = SessionMachine()
    result = session.start()
    assert result.segment_sequence == 1
    assert result.enqueue_initial_turn is True
    assert session.recording_status is RecordingStatus.RUNNING
    assert session.source_status.value == SourceStatus.WAITING_FOR_SOURCE.value
    assert session.agent_status is AgentStatus.STARTING


def test_source_can_be_selected_and_lost_while_session_keeps_running() -> None:
    session = SessionMachine()
    session.start()
    session.select_source("meet-document")
    assert session.selected_sources == {SourceRole.SECONDARY: "meet-document"}
    assert session.source_status is SourceStatus.CAPTIONS_NOT_DETECTED
    session.lose_source("meet-document")
    assert session.recording_status is RecordingStatus.RUNNING
    assert session.source_status.value == SourceStatus.WAITING_FOR_SOURCE.value


def test_stop_and_restart_create_segment_without_repeating_initial_turn() -> None:
    session = SessionMachine()
    first = session.start()
    session.select_source("meet-document", captions_visible=True)
    session.begin_stop(boundary_offset_us=100)
    session.finish_stop()
    second = session.start()
    assert first.segment_sequence == 1
    assert first.enqueue_initial_turn is True
    assert second.segment_sequence == 2
    assert second.enqueue_initial_turn is False
    assert session.selected_sources == {}


def test_transitional_conflicts_and_repeated_stop_are_typed() -> None:
    session = SessionMachine(recording_status=RecordingStatus.STOPPING)
    with pytest.raises(TransitionRejected, match="session_transition_in_progress"):
        session.start()
    fresh = SessionMachine()
    fresh.finish_stop()
    assert fresh.recording_status is RecordingStatus.STOPPED
    stopped = SessionMachine(recording_status=RecordingStatus.STOPPED)
    stopped.begin_stop(boundary_offset_us=100)
    stopped.finish_stop()


def test_generated_transition_sequences_preserve_session_invariants() -> None:
    operations = ("start", "select", "lose", "begin_stop", "finish_stop")
    for sequence in product(operations, repeat=5):
        session = SessionMachine()
        previous_segment = 0
        for operation in sequence:
            try:
                if operation == "start":
                    session.start()
                elif operation == "select":
                    session.select_source("source-1", captions_visible=True)
                elif operation == "lose":
                    session.lose_source("source-1")
                elif operation == "begin_stop":
                    session.begin_stop(boundary_offset_us=100)
                else:
                    session.finish_stop()
            except TransitionRejected:
                pass

            assert session.segment_sequence >= previous_segment
            previous_segment = session.segment_sequence
            if session.recording_status is RecordingStatus.STOPPED:
                assert session.selected_sources == {}
                assert session.source_status is SourceStatus.NO_SOURCE
            if session.recording_status is RecordingStatus.RUNNING:
                assert session.stop_boundary_offset_us is None
