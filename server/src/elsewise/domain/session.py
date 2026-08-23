from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from elsewise.domain.states import AgentStatus, CaptureStatus, RecordingStatus
from elsewise.settings.limits import STOP_FINALIZE_GRACE_SECONDS


class TransitionRejected(ValueError):
    pass


@dataclass(frozen=True)
class StartResult:
    segment_sequence: int
    enqueue_initial_turn: bool


@dataclass
class SessionMachine:
    recording_status: RecordingStatus = RecordingStatus.IDLE
    capture_status: CaptureStatus = CaptureStatus.NO_SOURCE
    agent_status: AgentStatus = AgentStatus.NOT_STARTED
    enabled_source_id: str | None = None
    active_source_id: str | None = None
    segment_sequence: int = 0
    initial_turn_enqueued: bool = False
    finalize_grace_until: datetime | None = None
    finalize_grace_source_id: str | None = None

    def enable_source(self, source_id: str, *, captions_visible: bool = False) -> None:
        if (
            self.recording_status is RecordingStatus.RUNNING
            and self.active_source_id is not None
            and self.active_source_id != source_id
        ):
            raise TransitionRejected("source_switch_rejected")
        self.enabled_source_id = source_id
        if self.recording_status is RecordingStatus.RUNNING:
            self.active_source_id = source_id
            self.capture_status = (
                CaptureStatus.CAPTURING if captions_visible else CaptureStatus.CAPTIONS_NOT_DETECTED
            )
        elif self.capture_status is CaptureStatus.NO_SOURCE:
            self.capture_status = CaptureStatus.CONNECTED

    def start(self, *, now: datetime | None = None) -> StartResult:
        if self.recording_status is RecordingStatus.RUNNING:
            raise TransitionRejected("already_running")
        _ = now or datetime.now(UTC)
        self.recording_status = RecordingStatus.RUNNING
        self.segment_sequence += 1
        self.finalize_grace_until = None
        self.finalize_grace_source_id = None
        enqueue_initial = not self.initial_turn_enqueued
        self.initial_turn_enqueued = True
        if self.agent_status is AgentStatus.NOT_STARTED:
            self.agent_status = AgentStatus.STARTING
        if self.enabled_source_id is None:
            self.active_source_id = None
            self.capture_status = CaptureStatus.WAITING_FOR_SOURCE
        else:
            self.active_source_id = self.enabled_source_id
            self.capture_status = CaptureStatus.CAPTIONS_NOT_DETECTED
        return StartResult(self.segment_sequence, enqueue_initial)

    def stop(self, *, now: datetime | None = None) -> None:
        if self.recording_status is not RecordingStatus.RUNNING:
            raise TransitionRejected("not_running")
        stopped_at = now or datetime.now(UTC)
        self.recording_status = RecordingStatus.STOPPED
        self.finalize_grace_until = stopped_at + timedelta(seconds=STOP_FINALIZE_GRACE_SECONDS)
        self.finalize_grace_source_id = self.active_source_id
        self.active_source_id = None
        self.capture_status = (
            CaptureStatus.CONNECTED
            if self.enabled_source_id is not None
            else CaptureStatus.NO_SOURCE
        )

    def in_finalize_grace(self, at: datetime) -> bool:
        return self.finalize_grace_until is not None and at <= self.finalize_grace_until
