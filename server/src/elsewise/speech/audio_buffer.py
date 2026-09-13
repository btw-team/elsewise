from collections import deque
from dataclasses import dataclass

from elsewise.audio.protocol import CANONICAL_SAMPLE_RATE, AudioFrame


class AudioRegionUnavailable(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class BufferedAudioRegion:
    first_sample_position: int
    last_sample_position: int
    pcm: bytes


class RollingPcmBuffer:
    """A frame-aware RAM-only rolling buffer with time and byte hard bounds."""

    def __init__(
        self,
        *,
        maximum_seconds: float = 60.0,
        maximum_bytes: int = 16_000 * 4 * 60,
        sample_rate: int = CANONICAL_SAMPLE_RATE,
    ) -> None:
        if not 0 < maximum_seconds <= 60:
            raise ValueError("maximum_seconds must be between 0 and 60")
        if maximum_bytes < 4 or sample_rate < 1:
            raise ValueError("rolling buffer bounds must be positive")
        self.maximum_samples = int(maximum_seconds * sample_rate)
        self.maximum_bytes = maximum_bytes
        self.sample_rate = sample_rate
        self._frames: deque[AudioFrame] = deque()
        self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def append(self, frame: AudioFrame) -> None:
        if len(frame.pcm) > self.maximum_bytes:
            raise ValueError("a single audio frame exceeds the rolling buffer byte cap")
        self._frames.append(frame)
        self._bytes += len(frame.pcm)
        latest = frame.source_sample_position + frame.frame_samples
        minimum_position = max(0, latest - self.maximum_samples)
        while self._frames and (
            self._bytes > self.maximum_bytes
            or self._frames[0].source_sample_position + self._frames[0].frame_samples
            <= minimum_position
        ):
            removed = self._frames.popleft()
            self._bytes -= len(removed.pcm)

    def region(self, first_sample_position: int, last_sample_position: int) -> BufferedAudioRegion:
        if first_sample_position < 0 or last_sample_position <= first_sample_position:
            raise ValueError("audio region bounds must be ordered and non-empty")
        cursor = first_sample_position
        chunks: list[bytes] = []
        for frame in self._frames:
            frame_start = frame.source_sample_position
            frame_end = frame_start + frame.frame_samples
            if frame_end <= cursor:
                continue
            if frame_start > cursor:
                raise AudioRegionUnavailable("audio region contains a continuity gap")
            selected_end = min(frame_end, last_sample_position)
            byte_start = (cursor - frame_start) * 4
            byte_end = (selected_end - frame_start) * 4
            chunks.append(frame.pcm[byte_start:byte_end])
            cursor = selected_end
            if cursor == last_sample_position:
                return BufferedAudioRegion(
                    first_sample_position, last_sample_position, b"".join(chunks)
                )
        raise AudioRegionUnavailable("audio region has been evicted or is incomplete")

    def discard_before(self, sample_position: int) -> None:
        while (
            self._frames
            and self._frames[0].source_sample_position + self._frames[0].frame_samples
            <= sample_position
        ):
            removed = self._frames.popleft()
            self._bytes -= len(removed.pcm)

    def clear(self) -> None:
        self._frames.clear()
        self._bytes = 0
