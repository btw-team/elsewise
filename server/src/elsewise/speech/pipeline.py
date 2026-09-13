import asyncio
from uuid import UUID

from elsewise.audio.protocol import AudioFrame, AudioFrameFlags
from elsewise.persistence.database import Database
from elsewise.persistence.models import SessionSourceBindingRecord, SourceEpochRecord, utc_now
from elsewise.sources.contracts import SourceRole
from elsewise.speech.audio_buffer import AudioRegionUnavailable, RollingPcmBuffer
from elsewise.speech.contracts import (
    ASRBackend,
    ASRStream,
    AudioRegion,
    AudioRegionLeaseRegistry,
    SpeechEvent,
)
from elsewise.speech.projector import SpeechProjector


class SpeechOverloaded(RuntimeError):
    pass


class SpeechContinuityLost(RuntimeError):
    pass


class SpeechPipeline:
    def __init__(
        self,
        database: Database,
        *,
        epoch_id: str,
        backend: ASRBackend,
        language: str,
        maximum_queued_frames: int = 50,
        rolling_buffer: RollingPcmBuffer | None = None,
        region_consumers: AudioRegionLeaseRegistry | None = None,
    ) -> None:
        if maximum_queued_frames < 1:
            raise ValueError("maximum_queued_frames must be positive")
        self.database = database
        self.epoch_id = epoch_id
        self.backend = backend
        self.language = language
        self.projector = SpeechProjector(database)
        self.rolling_buffer = rolling_buffer or RollingPcmBuffer(maximum_bytes=16 * 1024 * 1024)
        self.region_consumers = region_consumers or AudioRegionLeaseRegistry()
        self._queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue(maximum_queued_frames)
        self._stream: ASRStream | None = None
        self._worker: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
        self._expected_sequence: int | None = None
        self._expected_sample_position: int | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stream = await self.backend.create_stream(language=self.language)
        self._worker = asyncio.create_task(self._run())

    def push(self, frame: AudioFrame) -> None:
        if self._worker is None or self._worker.done():
            raise RuntimeError("speech pipeline is not running")
        if str(frame.epoch_id) != str(UUID(self.epoch_id)):
            raise ValueError("audio frame belongs to another source epoch")
        if (
            self._expected_sequence is not None
            and (
                frame.sequence != self._expected_sequence
                or frame.source_sample_position != self._expected_sample_position
            )
            and not frame.flags & AudioFrameFlags.DISCONTINUITY
        ):
            self._record_failure("audio_discontinuity")
            failure = SpeechContinuityLost(
                "audio frame continuity was lost without a discontinuity boundary"
            )
            self._failure = failure
            raise failure
        self._expected_sequence = frame.sequence + 1
        self._expected_sample_position = frame.source_sample_position + frame.frame_samples
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull as exc:
            self._record_overload()
            raise SpeechOverloaded("speech frame queue is full") from exc

    async def stop(self, *, timeout_seconds: float) -> None:
        worker = self._worker
        if worker is None:
            return
        try:
            await asyncio.wait_for(self._queue.put(None), timeout=timeout_seconds)
            await asyncio.wait_for(worker, timeout=timeout_seconds)
        except TimeoutError:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            self._record_failure("asr_flush_timeout")
            raise
        finally:
            self._worker = None
            self._stream = None
            self.rolling_buffer.clear()
        if self._failure is not None:
            raise RuntimeError("speech worker failed") from self._failure

    async def _run(self) -> None:
        assert self._stream is not None
        try:
            while True:
                frame = await self._queue.get()
                if frame is None:
                    break
                self._record_frame(frame)
                await self._project(await self._stream.push_audio(frame))
            await self._project(await self._stream.flush())
        except BaseException as exc:
            self._failure = exc
            self._record_failure("asr_failed")
        finally:
            await self._stream.close()

    async def _project(self, events: tuple[SpeechEvent, ...]) -> None:
        for event in events:
            result = self.projector.process(self.epoch_id, event, self.backend)
            if result == "applied" and event.kind == "final":
                await self._dispatch_region(event)

    def _record_frame(self, frame: AudioFrame) -> None:
        self.rolling_buffer.append(frame)
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, self.epoch_id)
            if epoch is None:
                return
            epoch.first_sequence = (
                frame.sequence if epoch.first_sequence is None else epoch.first_sequence
            )
            epoch.last_sequence = frame.sequence
            epoch.first_sample_position = (
                frame.source_sample_position
                if epoch.first_sample_position is None
                else epoch.first_sample_position
            )
            epoch.last_sample_position = frame.source_sample_position + frame.frame_samples
            epoch.received_event_count += 1
            epoch.last_seen_at = utc_now()
            if frame.flags & AudioFrameFlags.DISCONTINUITY:
                epoch.discontinuity_count += 1
            if frame.flags & AudioFrameFlags.XRUN:
                epoch.xrun_count += 1

    async def _dispatch_region(self, event: SpeechEvent) -> None:
        if not self.region_consumers.has_consumers:
            self.rolling_buffer.discard_before(event.last_sample_position)
            return
        try:
            buffered = self.rolling_buffer.region(
                event.first_sample_position, event.last_sample_position
            )
        except AudioRegionUnavailable:
            self._record_failure("audio_region_unavailable")
            return
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, self.epoch_id)
            binding = (
                db.get(SessionSourceBindingRecord, epoch.binding_id)
                if epoch is not None and epoch.binding_id is not None
                else None
            )
            role = SourceRole(binding.role) if binding is not None else SourceRole.REMOTE
        await self.region_consumers.dispatch(
            AudioRegion(
                source_epoch_id=self.epoch_id,
                utterance_id=event.utterance_id,
                role=role,
                first_sample_position=buffered.first_sample_position,
                last_sample_position=buffered.last_sample_position,
                sample_rate=self.rolling_buffer.sample_rate,
                samples=memoryview(buffered.pcm),
            )
        )
        self.rolling_buffer.discard_before(event.last_sample_position)

    def _record_overload(self) -> None:
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, self.epoch_id)
            if epoch is not None:
                epoch.dropped_event_count += 1
                epoch.discontinuity_count += 1
                epoch.last_health_status = "degraded"
                epoch.last_error_code = "ipc_backpressure"

    def _record_failure(self, error_code: str) -> None:
        with self.database.transaction() as db:
            epoch = db.get(SourceEpochRecord, self.epoch_id)
            if epoch is not None:
                epoch.last_health_status = "degraded"
                epoch.last_error_code = error_code
