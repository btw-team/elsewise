from dataclasses import dataclass

from elsewise.domain.states import AgentStatus, RecordingStatus, SourceStatus


class TransitionRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StartResult:
    segment_sequence: int
    enqueue_initial_turn: bool


@dataclass(slots=True)
class SessionMachine:
    recording_status: RecordingStatus = RecordingStatus.STOPPED
    source_status: SourceStatus = SourceStatus.NO_SOURCE
    agent_status: AgentStatus = AgentStatus.NOT_STARTED
    selected_source_id: str | None = None
    segment_sequence: int = 0
    initial_turn_enqueued: bool = False
    stop_boundary_offset_us: int | None = None

    def start(self) -> StartResult:
        if self.recording_status is RecordingStatus.STOPPING:
            raise TransitionRejected("session_transition_in_progress")
        if self.recording_status is RecordingStatus.RUNNING:
            return StartResult(self.segment_sequence, False)
        self.recording_status = RecordingStatus.STARTING
        self.segment_sequence += 1
        self.selected_source_id = None
        self.source_status = SourceStatus.WAITING_FOR_SOURCE
        self.stop_boundary_offset_us = None
        enqueue = not self.initial_turn_enqueued
        self.initial_turn_enqueued = True
        if self.agent_status is AgentStatus.NOT_STARTED:
            self.agent_status = AgentStatus.STARTING
        self.recording_status = RecordingStatus.RUNNING
        return StartResult(self.segment_sequence, enqueue)

    def select_source(self, source_id: str, *, captions_visible: bool = False) -> None:
        if self.recording_status is not RecordingStatus.RUNNING:
            raise TransitionRejected("session_not_running")
        self.selected_source_id = source_id
        self.source_status = (
            SourceStatus.CAPTURING if captions_visible else SourceStatus.CAPTIONS_NOT_DETECTED
        )

    def lose_source(self, source_id: str) -> None:
        if self.selected_source_id == source_id:
            self.source_status = SourceStatus.WAITING_FOR_SOURCE

    def begin_stop(self, *, boundary_offset_us: int) -> None:
        if self.recording_status is RecordingStatus.STOPPED:
            return
        if self.recording_status is not RecordingStatus.RUNNING:
            raise TransitionRejected("session_not_running")
        self.recording_status = RecordingStatus.STOPPING
        self.stop_boundary_offset_us = boundary_offset_us

    def finish_stop(self) -> None:
        if self.recording_status is RecordingStatus.STOPPED:
            return
        if self.recording_status is not RecordingStatus.STOPPING:
            raise TransitionRejected("session_not_stopping")
        self.recording_status = RecordingStatus.STOPPED
        self.selected_source_id = None
        self.source_status = SourceStatus.NO_SOURCE
