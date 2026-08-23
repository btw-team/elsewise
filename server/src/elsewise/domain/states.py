from enum import StrEnum


class RecordingStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"


class CaptureStatus(StrEnum):
    NO_SOURCE = "no_source"
    WAITING_FOR_SOURCE = "waiting_for_source"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CAPTIONS_NOT_DETECTED = "captions_not_detected"
    CAPTURING = "capturing"
    DISCONNECTED = "disconnected"
    ERROR = "error"


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
