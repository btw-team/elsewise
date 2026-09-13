from dataclasses import dataclass, field
from typing import Literal

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
