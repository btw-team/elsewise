from dataclasses import dataclass, field

from elsewise.audio.protocol import AudioFrame
from elsewise.speech.contracts import ASRStream, SpeechEvent


@dataclass(slots=True)
class FakeASRStream:
    events_by_sequence: dict[int, tuple[SpeechEvent, ...]]
    flush_events: tuple[SpeechEvent, ...] = ()
    closed: bool = False

    async def push_audio(self, frame: AudioFrame) -> tuple[SpeechEvent, ...]:
        if self.closed:
            raise RuntimeError("ASR stream is closed")
        return self.events_by_sequence.get(frame.sequence, ())

    async def flush(self) -> tuple[SpeechEvent, ...]:
        if self.closed:
            return ()
        return self.flush_events

    async def close(self) -> None:
        self.closed = True


@dataclass(frozen=True, slots=True)
class FakeASRBackend:
    events_by_sequence: dict[int, tuple[SpeechEvent, ...]] = field(default_factory=dict)
    flush_events: tuple[SpeechEvent, ...] = ()
    id: str = "fake"
    version: str = "1"
    model_id: str = "fake-deterministic"
    model_version: str = "1"
    capabilities: frozenset[str] = frozenset({"streaming", "timestamps"})

    async def create_stream(self, *, language: str) -> ASRStream:
        if not language:
            raise ValueError("language is required")
        return FakeASRStream(dict(self.events_by_sequence), self.flush_events)
