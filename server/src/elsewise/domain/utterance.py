from dataclasses import dataclass, field
from enum import StrEnum


class ApplyResult(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    STALE = "stale"
    SOURCE_NOT_BOUND = "source_not_bound"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class UtteranceEvent:
    event_id: str
    source_epoch_id: str
    utterance_id: str
    revision: int
    text: str
    session_offset_us: int
    final: bool = False


@dataclass(slots=True)
class Utterance:
    source_epoch_id: str
    utterance_id: str
    revision: int
    text: str
    session_offset_us: int
    final: bool


@dataclass(slots=True)
class UtteranceMachine:
    utterances: dict[tuple[str, str], Utterance] = field(default_factory=dict)
    seen_event_ids: set[str] = field(default_factory=set)

    def apply(
        self,
        event: UtteranceEvent,
        *,
        bound_epoch_id: str,
        stop_boundary_offset_us: int | None = None,
    ) -> ApplyResult:
        if event.event_id in self.seen_event_ids:
            return ApplyResult.DUPLICATE
        self.seen_event_ids.add(event.event_id)
        if event.source_epoch_id != bound_epoch_id:
            return ApplyResult.SOURCE_NOT_BOUND
        if (
            stop_boundary_offset_us is not None
            and event.session_offset_us > stop_boundary_offset_us
        ):
            return ApplyResult.REJECTED
        key = (event.source_epoch_id, event.utterance_id)
        existing = self.utterances.get(key)
        if existing is not None:
            if existing.final:
                return ApplyResult.REJECTED
            if event.revision < existing.revision or (
                event.revision == existing.revision and not event.final
            ):
                return ApplyResult.STALE
        self.utterances[key] = Utterance(
            source_epoch_id=event.source_epoch_id,
            utterance_id=event.utterance_id,
            revision=event.revision,
            text=event.text,
            session_offset_us=event.session_offset_us,
            final=event.final,
        )
        return ApplyResult.APPLIED
