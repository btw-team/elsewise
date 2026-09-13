import math
import struct
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from elsewise.audio.protocol import AudioFrame, AudioFrameFlags


class VoiceActivityDetector(Protocol):
    def is_speech(self, frame: AudioFrame) -> bool: ...


class EnergyVad:
    """Deterministic test/emergency VAD; production profiles use a model-backed adapter."""

    def __init__(self, *, rms_threshold: float = 0.01) -> None:
        if not 0 < rms_threshold <= 1:
            raise ValueError("rms_threshold must be between 0 and 1")
        self.rms_threshold = rms_threshold

    def is_speech(self, frame: AudioFrame) -> bool:
        if not frame.pcm:
            return False
        values = struct.iter_unpack("<f", frame.pcm)
        mean_square = sum(value[0] * value[0] for value in values) / frame.frame_samples
        return math.sqrt(mean_square) >= self.rms_threshold


@dataclass(frozen=True, slots=True)
class EndpointingConfig:
    start_frames: int = 2
    end_silence_frames: int = 20
    preroll_frames: int = 5
    maximum_phrase_frames: int = 3_000

    def __post_init__(self) -> None:
        if self.start_frames < 1 or self.end_silence_frames < 1:
            raise ValueError("endpoint frame thresholds must be positive")
        if self.preroll_frames < 0 or self.preroll_frames > 100:
            raise ValueError("preroll_frames is outside the supported bound")
        if self.maximum_phrase_frames < self.start_frames:
            raise ValueError("maximum_phrase_frames is too small")


class EndpointKind(StrEnum):
    START = "start"
    AUDIO = "audio"
    END = "end"
    DISCONTINUITY = "discontinuity"


@dataclass(frozen=True, slots=True)
class EndpointEvent:
    kind: EndpointKind
    frames: tuple[AudioFrame, ...] = ()
    reason: str | None = None


class EndpointDetector:
    def __init__(self, vad: VoiceActivityDetector, config: EndpointingConfig | None = None) -> None:
        self.vad = vad
        self.config = config or EndpointingConfig()
        self._preroll: deque[AudioFrame] = deque(maxlen=self.config.preroll_frames)
        self._active = False
        self._speech_run = 0
        self._silence_run = 0
        self._phrase_frames = 0

    def process(self, frame: AudioFrame) -> tuple[EndpointEvent, ...]:
        if frame.flags & (AudioFrameFlags.DISCONTINUITY | AudioFrameFlags.XRUN):
            boundary_events = self._end("audio_discontinuity")
            self._preroll.clear()
            self._speech_run = 0
            return (
                *boundary_events,
                EndpointEvent(EndpointKind.DISCONTINUITY, reason="audio_discontinuity"),
            )
        speech = self.vad.is_speech(frame)
        if not self._active:
            self._preroll.append(frame)
            self._speech_run = self._speech_run + 1 if speech else 0
            if self._speech_run < self.config.start_frames:
                return ()
            self._active = True
            self._phrase_frames = len(self._preroll)
            self._silence_run = 0
            frames = tuple(self._preroll)
            self._preroll.clear()
            return (EndpointEvent(EndpointKind.START, frames),)

        self._phrase_frames += 1
        self._silence_run = 0 if speech else self._silence_run + 1
        events: list[EndpointEvent] = [EndpointEvent(EndpointKind.AUDIO, (frame,))]
        if self._silence_run >= self.config.end_silence_frames:
            events.extend(self._end("silence"))
        elif self._phrase_frames >= self.config.maximum_phrase_frames:
            events.extend(self._end("maximum_phrase"))
        return tuple(events)

    def flush(self) -> tuple[EndpointEvent, ...]:
        events = self._end("flush")
        self._preroll.clear()
        self._speech_run = 0
        return events

    def _end(self, reason: str) -> tuple[EndpointEvent, ...]:
        if not self._active:
            return ()
        self._active = False
        self._speech_run = 0
        self._silence_run = 0
        self._phrase_frames = 0
        return (EndpointEvent(EndpointKind.END, reason=reason),)
