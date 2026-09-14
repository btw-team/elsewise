from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from elsewise.audio.protocol import AudioFrame
from elsewise.speech.contracts import ASRStream, SpeechEvent
from elsewise.speech.worker_supervisor import SpeechWorkerSupervisor


class SherpaOnnxStream:
    def __init__(self, supervisor: SpeechWorkerSupervisor, stream_id: str) -> None:
        self.supervisor = supervisor
        self.stream_id = stream_id
        self.closed = False

    async def push_audio(self, frame: AudioFrame) -> tuple[SpeechEvent, ...]:
        if self.closed:
            raise RuntimeError("ASR stream is closed")
        return await self.supervisor.push_audio(self.stream_id, frame)

    async def flush(self) -> tuple[SpeechEvent, ...]:
        if self.closed:
            return ()
        return await self.supervisor.flush_stream(self.stream_id)

    async def close(self) -> None:
        if self.closed:
            return
        await self.supervisor.close_stream(self.stream_id)
        self.closed = True


SpeechProfileName = Literal["conservative", "standard", "best"]


@dataclass(frozen=True, slots=True)
class SherpaOnnxBackend:
    supervisor: SpeechWorkerSupervisor
    profile: SpeechProfileName
    model_root: Path
    silero_model: Path
    finalizer_root: Path | None = None
    threads: int = 4
    id: str = "sherpa-onnx"
    version: str = "1.13.3"
    model_version: str = "development-inventory"

    def __post_init__(self) -> None:
        if not 1 <= self.threads <= 32:
            raise ValueError("threads must be between 1 and 32")
        if self.profile == "best" and self.finalizer_root is None:
            raise ValueError("best profile requires a finalizer model")

    @property
    def model_id(self) -> str:
        if self.profile == "conservative":
            return "whisper-base-int8"
        if self.profile == "standard":
            return "nemotron-3.5-streaming-0.6b-560ms-int8"
        return "nemotron-3.5-streaming-0.6b-560ms-int8+parakeet-tdt-0.6b-v3-int8"

    @property
    def capabilities(self) -> frozenset[str]:
        if self.profile == "conservative":
            return frozenset({"offline", "vad", "timestamps"})
        if self.profile == "standard":
            return frozenset({"streaming_model", "vad", "timestamps"})
        return frozenset({"streaming_model", "offline_finalizer", "vad", "timestamps", "revisions"})

    async def create_stream(self, *, language: str) -> ASRStream:
        if not language or len(language) > 32:
            raise ValueError("language must contain between 1 and 32 characters")
        stream_id = str(uuid4())
        await self.supervisor.create_stream(
            stream_id=stream_id,
            profile=self.profile,
            language=language,
            model_root=self.model_root,
            silero_model=self.silero_model,
            finalizer_root=self.finalizer_root,
            threads=self.threads,
        )
        return SherpaOnnxStream(self.supervisor, stream_id)
