from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AccessibilityHealth:
    status: str
    backend: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AccessibilityProcess:
    pid: int
    name: str


@dataclass(frozen=True, slots=True)
class AccessibilityNode:
    role: str
    name: str | None = None
    value: str | None = None
    description: str | None = None
    states: tuple[str, ...] = ()
    children: tuple["AccessibilityNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AccessibilityObservation:
    capability: str
    kind: str
    interval_start_us: int
    interval_end_us: int
    provenance: str
    confidence: float
    payload: Mapping[str, Any] = field(default_factory=dict)


class AccessibilityAdapter(Protocol):
    id: str

    def capabilities(self) -> frozenset[str]: ...

    def start(
        self,
        emit: Callable[[AccessibilityObservation], None],
        health: Callable[[AccessibilityHealth], None],
    ) -> None: ...

    def stop(self) -> None: ...


class AccessibilityBackend(Protocol):
    id: str

    def health(self) -> AccessibilityHealth: ...

    def processes(self) -> tuple[AccessibilityProcess, ...]: ...

    def snapshot(self, pid: int, *, max_depth: int, max_nodes: int) -> AccessibilityNode: ...
