from enum import StrEnum


class RecordingStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class SourceStatus(StrEnum):
    NO_SOURCE = "no_source"
    WAITING_FOR_SOURCE = "waiting_for_source"
    CAPTIONS_NOT_DETECTED = "captions_not_detected"
    CAPTURING = "capturing"
    DEGRADED = "degraded"


class AgentStatus(StrEnum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
