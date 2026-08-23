from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from elsewise.domain.session import SessionMachine
from elsewise.domain.states import RecordingStatus


class ApplyResult(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    STALE = "stale"
    NO_ACTIVE_SESSION = "no_active_session"
    SOURCE_NOT_BOUND = "source_not_bound"
    GRACE_FINALIZE_APPLIED = "grace_finalize_applied"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CaptionEvent:
    event_id: str
    source_id: str
    utterance_id: str
    revision: int
    speaker: str | None
    text: str
    observed_at: datetime


@dataclass
class Utterance:
    source_id: str
    utterance_id: str
    revision: int
    speaker: str | None
    text: str
    observed_at: datetime
    final: bool = False


@dataclass
class UtteranceMachine:
    utterances: dict[tuple[str, str], Utterance] = field(default_factory=dict)
    seen_event_ids: set[str] = field(default_factory=set)

    def upsert(self, event: CaptionEvent, session: SessionMachine) -> ApplyResult:
        if not self._mark_new(event.event_id):
            return ApplyResult.DUPLICATE
        if session.recording_status is not RecordingStatus.RUNNING:
            return ApplyResult.NO_ACTIVE_SESSION
        if session.active_source_id != event.source_id:
            return ApplyResult.SOURCE_NOT_BOUND
        return self._apply(event, finalize=False)

    def finalize(self, event: CaptionEvent, session: SessionMachine) -> ApplyResult:
        if not self._mark_new(event.event_id):
            return ApplyResult.DUPLICATE
        key = (event.source_id, event.utterance_id)
        existing = self.utterances.get(key)
        in_grace = (
            session.recording_status is RecordingStatus.STOPPED
            and session.in_finalize_grace(event.observed_at)
        )
        if session.recording_status is RecordingStatus.RUNNING:
            if session.active_source_id != event.source_id:
                return ApplyResult.SOURCE_NOT_BOUND
        elif not in_grace:
            return ApplyResult.NO_ACTIVE_SESSION
        elif (
            existing is None
            or existing.final
            or session.finalize_grace_source_id != event.source_id
        ):
            return ApplyResult.REJECTED

        result = self._apply(event, finalize=True)
        if result is ApplyResult.APPLIED and in_grace:
            return ApplyResult.GRACE_FINALIZE_APPLIED
        return result

    def _mark_new(self, event_id: str) -> bool:
        if event_id in self.seen_event_ids:
            return False
        self.seen_event_ids.add(event_id)
        return True

    def _apply(self, event: CaptionEvent, *, finalize: bool) -> ApplyResult:
        key = (event.source_id, event.utterance_id)
        existing = self.utterances.get(key)
        if existing is not None:
            if existing.final:
                return ApplyResult.REJECTED
            if event.revision < existing.revision:
                return ApplyResult.STALE
            if event.revision == existing.revision and not finalize:
                return ApplyResult.STALE
        self.utterances[key] = Utterance(
            source_id=event.source_id,
            utterance_id=event.utterance_id,
            revision=event.revision,
            speaker=event.speaker,
            text=event.text,
            observed_at=event.observed_at,
            final=finalize,
        )
        return ApplyResult.APPLIED
