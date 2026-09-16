from collections import deque
from dataclasses import dataclass
from threading import RLock

from elsewise.evidence.contracts import EvidenceEvent


@dataclass(frozen=True, slots=True)
class ActiveSpeakerInterval:
    source_epoch_id: str
    participant_id: str
    start_us: int
    end_us: int
    confidence: float
    evidence_event_ids: tuple[str, ...]


class ActiveSpeakerIndex:
    """Bounded transient interval state for later speaker-evidence joins."""

    def __init__(self, *, max_intervals: int = 2_048, max_open: int = 256) -> None:
        if max_intervals < 1 or max_open < 1:
            raise ValueError("active speaker index bounds are invalid")
        self._intervals: deque[ActiveSpeakerInterval] = deque(maxlen=max_intervals)
        self._open: dict[tuple[str, str], EvidenceEvent] = {}
        self._max_open = max_open
        self._lock = RLock()

    def consume(self, event: EvidenceEvent) -> None:
        if event.kind not in {"speaker.started", "speaker.stopped"}:
            return
        participant_id = event.payload.get("participant_id")
        if not isinstance(participant_id, str) or not participant_id:
            return
        key = (event.source_epoch_id, participant_id)
        with self._lock:
            if event.kind == "speaker.started":
                if key not in self._open and len(self._open) >= self._max_open:
                    oldest = min(
                        self._open,
                        key=lambda candidate: self._open[candidate].interval_start_us,
                    )
                    self._open.pop(oldest, None)
                self._open[key] = event
                return
            started = self._open.pop(key, None)
            if started is None:
                return
            self._intervals.append(
                ActiveSpeakerInterval(
                    source_epoch_id=event.source_epoch_id,
                    participant_id=participant_id,
                    start_us=started.interval_start_us,
                    end_us=max(started.interval_start_us, event.interval_end_us),
                    confidence=min(started.confidence, event.confidence),
                    evidence_event_ids=(started.event_id, event.event_id),
                )
            )

    def intervals(
        self, *, start_us: int | None = None, end_us: int | None = None
    ) -> tuple[ActiveSpeakerInterval, ...]:
        with self._lock:
            values = tuple(self._intervals)
        return tuple(
            item
            for item in values
            if (start_us is None or item.end_us >= start_us)
            and (end_us is None or item.start_us <= end_us)
        )

    def clear_epoch(self, source_epoch_id: str) -> None:
        with self._lock:
            for key in tuple(self._open):
                if key[0] == source_epoch_id:
                    self._open.pop(key, None)
