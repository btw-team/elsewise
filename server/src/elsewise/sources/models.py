from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

SourceState = Literal[
    "discovered",
    "starting",
    "running",
    "stopping",
    "stopped",
    "unavailable",
    "failed",
]
HealthStatus = Literal["available", "waiting", "degraded", "unavailable", "failed"]


@dataclass(frozen=True, slots=True)
class SourceHealth:
    status: HealthStatus
    error_code: str | None = None
    counters: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: str
    source_id: str
    source_epoch_id: str
    session_offset_us: int
    source_time_us: int | None
    kind: str
    payload: dict[str, Any]
    received_at: datetime
