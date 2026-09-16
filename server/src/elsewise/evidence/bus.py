from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from elsewise.evidence.contracts import EvidenceEvent


class PublishResult(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class EvidenceBusSnapshot:
    queued: int
    accepted: int
    duplicates: int
    rejected: int
    evicted: int


EvidenceConsumer = Callable[[EvidenceEvent], None]


class EvidenceBus:
    """Bounded, in-memory evidence fan-out with a bounded idempotency window."""

    def __init__(self, *, max_events: int = 2_048, dedupe_size: int = 8_192) -> None:
        if max_events < 1 or dedupe_size < max_events:
            raise ValueError("evidence bounds are invalid")
        self._events: deque[EvidenceEvent] = deque(maxlen=max_events)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._dedupe_size = dedupe_size
        self._consumers: dict[str, EvidenceConsumer] = {}
        self._lock = RLock()
        self._accepted = 0
        self._duplicates = 0
        self._rejected = 0
        self._evicted = 0

    def subscribe(self, name: str, consumer: EvidenceConsumer) -> None:
        if not name or len(name) > 128:
            raise ValueError("consumer name must be bounded")
        with self._lock:
            if name in self._consumers:
                raise ValueError(f"evidence consumer already registered: {name}")
            self._consumers[name] = consumer

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            self._consumers.pop(name, None)

    def publish(self, event: EvidenceEvent) -> PublishResult:
        with self._lock:
            if event.event_id in self._seen:
                self._duplicates += 1
                return PublishResult.DUPLICATE
            consumers = tuple(self._consumers.values())
            if len(self._events) == self._events.maxlen:
                self._evicted += 1
            self._events.append(event)
            self._seen[event.event_id] = None
            while len(self._seen) > self._dedupe_size:
                self._seen.popitem(last=False)
            self._accepted += 1

        failed = False
        for consumer in consumers:
            try:
                consumer(event)
            except Exception:
                failed = True
        if failed:
            with self._lock:
                self._rejected += 1
            return PublishResult.REJECTED
        return PublishResult.ACCEPTED

    def events(self) -> tuple[EvidenceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def snapshot(self) -> EvidenceBusSnapshot:
        with self._lock:
            return EvidenceBusSnapshot(
                queued=len(self._events),
                accepted=self._accepted,
                duplicates=self._duplicates,
                rejected=self._rejected,
                evicted=self._evicted,
            )
