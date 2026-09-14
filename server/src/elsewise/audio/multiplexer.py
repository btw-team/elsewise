import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from elsewise.audio.helper_process import AudioHelperError, AudioHelperSupervisor
from elsewise.audio.protocol import AudioFrame, AudioFrameFlags


@dataclass(slots=True)
class _StreamInbox:
    epoch_id: UUID
    queue: asyncio.Queue[AudioFrame | AudioHelperError | None]


class AudioStreamHandle:
    def __init__(
        self,
        multiplexer: "AudioFrameMultiplexer",
        source_id: UUID,
        epoch_id: UUID,
        inbox: _StreamInbox,
    ) -> None:
        self._multiplexer = multiplexer
        self.source_id = source_id
        self.epoch_id = epoch_id
        self._inbox = inbox

    async def frames(self) -> AsyncIterator[AudioFrame]:
        while True:
            item = await self._inbox.queue.get()
            if item is None:
                return
            if isinstance(item, AudioHelperError):
                raise item
            yield item

    async def stop(self) -> None:
        await self._multiplexer.stop(self.source_id)


class AudioFrameMultiplexer:
    """Routes one helper data connection into bounded, independent lane queues."""

    def __init__(
        self,
        helper: AudioHelperSupervisor,
        *,
        maximum_queued_frames_per_stream: int = 50,
    ) -> None:
        if maximum_queued_frames_per_stream < 1:
            raise ValueError("maximum_queued_frames_per_stream must be positive")
        self.helper = helper
        self.maximum_queued_frames_per_stream = maximum_queued_frames_per_stream
        self._streams: dict[UUID, _StreamInbox] = {}
        self._ignored_until_eos: set[UUID] = set()
        self._reader_task: asyncio.Task[None] | None = None
        self._stop_tasks: set[asyncio.Task[object]] = set()
        self._lock = asyncio.Lock()
        self._closing = False

    async def start_synthetic(
        self,
        *,
        source_id: UUID,
        epoch_id: UUID,
        frame_count: int,
    ) -> AudioStreamHandle:
        async with self._lock:
            if self._closing:
                raise AudioHelperError("audio frame multiplexer is closing")
            if source_id in self._streams or source_id in self._ignored_until_eos:
                raise AudioHelperError("audio source is already registered")
            await self.helper.start()
            inbox = _StreamInbox(
                epoch_id=epoch_id,
                queue=asyncio.Queue(self.maximum_queued_frames_per_stream + 1),
            )
            self._streams[source_id] = inbox
            if self._reader_task is None or self._reader_task.done():
                self._reader_task = asyncio.create_task(
                    self._read_loop(), name="elsewise-audio-frame-multiplexer"
                )
            try:
                await self.helper.start_synthetic_source(
                    source_id=source_id,
                    epoch_id=epoch_id,
                    frame_count=frame_count,
                )
            except BaseException:
                self._streams.pop(source_id, None)
                raise
            return AudioStreamHandle(self, source_id, epoch_id, inbox)

    async def start_native(
        self,
        *,
        source_kind: Literal["native_microphone", "native_process_audio", "native_system_audio"],
        source_id: UUID,
        epoch_id: UUID,
        target_key: str = "default",
    ) -> AudioStreamHandle:
        async with self._lock:
            await self.helper.start()
            inbox = self._register_stream(source_id=source_id, epoch_id=epoch_id)
            try:
                await self.helper.start_native_source(
                    source_kind=source_kind,
                    source_id=source_id,
                    epoch_id=epoch_id,
                    target_key=target_key,
                )
            except BaseException:
                self._streams.pop(source_id, None)
                raise
            return AudioStreamHandle(self, source_id, epoch_id, inbox)

    async def stop(self, source_id: UUID) -> None:
        async with self._lock:
            if source_id not in self._streams:
                return
            await self.helper.stop_source(source_id)

    async def close(self) -> None:
        async with self._lock:
            self._closing = True
            for inbox in self._streams.values():
                self._replace_queue(inbox, None)
            self._streams.clear()
            reader_task = self._reader_task
            self._reader_task = None
            if reader_task is not None:
                reader_task.cancel()
                await asyncio.gather(reader_task, return_exceptions=True)
            for task in self._stop_tasks:
                task.cancel()
            if self._stop_tasks:
                await asyncio.gather(*self._stop_tasks, return_exceptions=True)
            self._stop_tasks.clear()
            self._ignored_until_eos.clear()
            await self.helper.close()
            self._closing = False

    async def _read_loop(self) -> None:
        try:
            while True:
                frame = await self.helper.read_frame()
                if frame.source_id in self._ignored_until_eos:
                    if frame.flags & AudioFrameFlags.END_OF_STREAM:
                        self._ignored_until_eos.discard(frame.source_id)
                    continue
                inbox = self._streams.get(frame.source_id)
                if inbox is None:
                    raise AudioHelperError("helper returned a frame for an unknown source")
                if frame.epoch_id != inbox.epoch_id:
                    raise AudioHelperError("helper returned a frame for the wrong source epoch")
                if inbox.queue.qsize() >= self.maximum_queued_frames_per_stream:
                    self._fail_overloaded_stream(frame.source_id, inbox)
                    continue
                inbox.queue.put_nowait(frame)
                if frame.flags & AudioFrameFlags.END_OF_STREAM:
                    inbox.queue.put_nowait(None)
                    self._streams.pop(frame.source_id, None)
        except asyncio.CancelledError:
            raise
        except AudioHelperError as exc:
            for inbox in self._streams.values():
                self._replace_queue(inbox, exc)
            self._streams.clear()

    def _fail_overloaded_stream(self, source_id: UUID, inbox: _StreamInbox) -> None:
        error = AudioHelperError("audio lane queue overflowed; stream was stopped")
        self._replace_queue(inbox, error)
        self._streams.pop(source_id, None)
        self._ignored_until_eos.add(source_id)
        task = asyncio.create_task(self.helper.stop_source(source_id))
        self._stop_tasks.add(task)
        task.add_done_callback(self._stop_tasks.discard)

    def _register_stream(self, *, source_id: UUID, epoch_id: UUID) -> _StreamInbox:
        if self._closing:
            raise AudioHelperError("audio frame multiplexer is closing")
        if source_id in self._streams or source_id in self._ignored_until_eos:
            raise AudioHelperError("audio source is already registered")
        inbox = _StreamInbox(
            epoch_id=epoch_id,
            queue=asyncio.Queue(self.maximum_queued_frames_per_stream + 1),
        )
        self._streams[source_id] = inbox
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="elsewise-audio-frame-multiplexer"
            )
        return inbox

    @staticmethod
    def _replace_queue(inbox: _StreamInbox, item: AudioHelperError | None) -> None:
        with contextlib.suppress(asyncio.QueueEmpty):
            while True:
                inbox.queue.get_nowait()
        inbox.queue.put_nowait(item)
