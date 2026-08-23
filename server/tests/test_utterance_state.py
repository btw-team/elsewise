from datetime import UTC, datetime, timedelta

from elsewise.domain.session import SessionMachine
from elsewise.domain.utterance import ApplyResult, CaptionEvent, UtteranceMachine

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def event(event_id: str, *, revision: int, text: str = "hello") -> CaptionEvent:
    return CaptionEvent(
        event_id=event_id,
        source_id="meet-document",
        utterance_id="caption-1",
        revision=revision,
        speaker="Иван",
        text=text,
        observed_at=NOW,
    )


def running_session() -> SessionMachine:
    session = SessionMachine()
    session.enable_source("meet-document")
    session.start(now=NOW)
    return session


def test_duplicate_stale_newer_and_finalize_are_deterministic() -> None:
    session = running_session()
    machine = UtteranceMachine()
    first = event("event-1", revision=1)
    assert machine.upsert(first, session) is ApplyResult.APPLIED
    assert machine.upsert(first, session) is ApplyResult.DUPLICATE
    assert machine.upsert(event("event-2", revision=1), session) is ApplyResult.STALE
    assert (
        machine.upsert(event("event-3", revision=2, text="hello world"), session)
        is ApplyResult.APPLIED
    )
    assert (
        machine.finalize(event("event-4", revision=2, text="hello world"), session)
        is ApplyResult.APPLIED
    )
    stored = machine.utterances[("meet-document", "caption-1")]
    assert stored.text == "hello world"
    assert stored.final is True
    assert (
        machine.upsert(event("event-5", revision=3, text="correction"), session)
        is ApplyResult.REJECTED
    )


def test_stop_grace_accepts_only_finalize_of_existing_partial() -> None:
    session = running_session()
    machine = UtteranceMachine()
    assert machine.upsert(event("event-1", revision=1), session) is ApplyResult.APPLIED
    session.stop(now=NOW)
    assert machine.upsert(event("event-2", revision=2), session) is ApplyResult.NO_ACTIVE_SESSION
    final = event("event-3", revision=1)
    assert machine.finalize(final, session) is ApplyResult.GRACE_FINALIZE_APPLIED


def test_stop_grace_rejects_new_or_late_finalize() -> None:
    session = running_session()
    machine = UtteranceMachine()
    session.stop(now=NOW)
    assert machine.finalize(event("event-1", revision=1), session) is ApplyResult.REJECTED
    partial = event("event-2", revision=1)
    session = running_session()
    assert machine.upsert(partial, session) is ApplyResult.APPLIED
    session.stop(now=NOW)
    late = CaptionEvent(
        **{**event("event-3", revision=1).__dict__, "observed_at": NOW + timedelta(seconds=3)}
    )
    assert machine.finalize(late, session) is ApplyResult.NO_ACTIVE_SESSION
