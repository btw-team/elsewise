from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from elsewise.audio.protocol import AudioFrame
from elsewise.sources.contracts import SourceRole

AudioRegionConsumer = Callable[["AudioRegion"], Awaitable[None]]
SpeechEventKind = Literal["partial", "final"]


@dataclass(frozen=True, slots=True)
class SpeechEvent:
    utterance_id: str
    revision: int
    kind: SpeechEventKind
    text: str
    first_sample_position: int
    last_sample_position: int
    confidence: float | None = None
    durable: bool = False

    def __post_init__(self) -> None:
        if not self.utterance_id or len(self.utterance_id) > 256:
            raise ValueError("utterance_id must be bounded")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if len(self.text) > 20_000:
            raise ValueError("speech text exceeds the protocol bound")
        if self.first_sample_position < 0 or self.last_sample_position < self.first_sample_position:
            raise ValueError("speech sample positions must be ordered")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.kind == "partial" and self.durable:
            raise ValueError("partial speech event cannot be durable")


class ASRStream(Protocol):
    async def push_audio(self, frame: AudioFrame) -> tuple[SpeechEvent, ...]: ...

    async def flush(self) -> tuple[SpeechEvent, ...]: ...

    async def close(self) -> None: ...


class ASRBackend(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    async def create_stream(self, *, language: str) -> ASRStream: ...


@dataclass(frozen=True, slots=True)
class AudioRegion:
    source_epoch_id: str
    utterance_id: str
    role: SourceRole
    first_sample_position: int
    last_sample_position: int
    sample_rate: int
    samples: memoryview

    def __post_init__(self) -> None:
        if not self.source_epoch_id or not self.utterance_id:
            raise ValueError("audio region identity is required")
        if self.first_sample_position < 0 or self.last_sample_position < self.first_sample_position:
            raise ValueError("audio sample positions must be ordered and non-negative")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")


class AudioRegionLeaseRegistry:
    def __init__(self, *, maximum_consumers: int = 8) -> None:
        if maximum_consumers < 1:
            raise ValueError("maximum_consumers must be positive")
        self.maximum_consumers = maximum_consumers
        self._consumers: dict[str, AudioRegionConsumer] = {}

    @property
    def has_consumers(self) -> bool:
        return bool(self._consumers)

    def register(self, consumer_id: str, consumer: AudioRegionConsumer) -> None:
        if not consumer_id or len(consumer_id) > 128:
            raise ValueError("consumer_id must contain between 1 and 128 characters")
        if consumer_id in self._consumers:
            raise ValueError(f"audio region consumer already registered: {consumer_id}")
        if len(self._consumers) >= self.maximum_consumers:
            raise ValueError("audio region consumer limit reached")
        self._consumers[consumer_id] = consumer

    def unregister(self, consumer_id: str) -> None:
        self._consumers.pop(consumer_id, None)

    async def dispatch(self, region: AudioRegion) -> tuple[str, ...]:
        delivered: list[str] = []
        for consumer_id, consumer in tuple(self._consumers.items()):
            await consumer(region)
            delivered.append(consumer_id)
        return tuple(delivered)
