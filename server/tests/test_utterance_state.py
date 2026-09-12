from elsewise.domain.utterance import ApplyResult, CaptionEvent, UtteranceMachine


def event(
    event_id: str,
    *,
    revision: int,
    offset: int = 10,
    text: str = "hello",
    final: bool = False,
    epoch: str = "epoch-1",
) -> CaptionEvent:
    return CaptionEvent(
        event_id=event_id,
        source_epoch_id=epoch,
        utterance_id="caption-1",
        revision=revision,
        text=text,
        session_offset_us=offset,
        final=final,
    )


def test_duplicate_stale_newer_and_finalize_are_deterministic() -> None:
    machine = UtteranceMachine()
    first = event("event-1", revision=1)
    assert machine.apply(first, bound_epoch_id="epoch-1") is ApplyResult.APPLIED
    assert machine.apply(first, bound_epoch_id="epoch-1") is ApplyResult.DUPLICATE
    assert (
        machine.apply(event("event-2", revision=1), bound_epoch_id="epoch-1") is ApplyResult.STALE
    )
    assert (
        machine.apply(event("event-3", revision=2, text="hello world"), bound_epoch_id="epoch-1")
        is ApplyResult.APPLIED
    )
    assert (
        machine.apply(
            event("event-4", revision=2, text="hello world", final=True), bound_epoch_id="epoch-1"
        )
        is ApplyResult.APPLIED
    )
    stored = machine.utterances[("epoch-1", "caption-1")]
    assert stored.text == "hello world"
    assert stored.final is True
    assert (
        machine.apply(event("event-5", revision=3), bound_epoch_id="epoch-1")
        is ApplyResult.REJECTED
    )


def test_epoch_binding_and_stop_boundary_reject_unrelated_or_late_evidence() -> None:
    machine = UtteranceMachine()
    assert (
        machine.apply(event("event-1", revision=1, epoch="epoch-2"), bound_epoch_id="epoch-1")
        is ApplyResult.SOURCE_NOT_BOUND
    )
    assert (
        machine.apply(
            event("event-2", revision=1, offset=101),
            bound_epoch_id="epoch-1",
            stop_boundary_offset_us=100,
        )
        is ApplyResult.REJECTED
    )
    assert (
        machine.apply(
            event("event-3", revision=1, offset=100),
            bound_epoch_id="epoch-1",
            stop_boundary_offset_us=100,
        )
        is ApplyResult.APPLIED
    )
