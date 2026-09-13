from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

MAX_EVIDENCE_PAYLOAD_FIELDS = 64
MAX_EVIDENCE_KIND_LENGTH = 128
MAX_PROVENANCE_LENGTH = 128
MAX_EVIDENCE_VALUE_LENGTH = 4096
MAX_EVIDENCE_COLLECTION_ITEMS = 64
MAX_EVIDENCE_DEPTH = 4


def _freeze_bounded(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_EVIDENCE_DEPTH:
        raise ValueError("evidence payload is nested too deeply")
    if isinstance(value, str):
        if len(value) > MAX_EVIDENCE_VALUE_LENGTH:
            raise ValueError("evidence payload string is too long")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_EVIDENCE_COLLECTION_ITEMS:
            raise ValueError("evidence payload mapping contains too many items")
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("evidence payload keys must be bounded strings")
            frozen[key] = _freeze_bounded(item, depth=depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_EVIDENCE_COLLECTION_ITEMS:
            raise ValueError("evidence payload sequence contains too many items")
        return tuple(_freeze_bounded(item, depth=depth + 1) for item in value)
    raise ValueError("evidence payload must contain JSON-compatible values")


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    event_id: str
    source_id: str
    source_epoch_id: str
    capability: str
    kind: str
    interval_start_us: int
    interval_end_us: int
    observed_monotonic_us: int
    timing_uncertainty_us: int
    provenance: str
    confidence: float
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value, maximum in (
            ("event_id", self.event_id, 256),
            ("source_id", self.source_id, 256),
            ("source_epoch_id", self.source_epoch_id, 256),
            ("capability", self.capability, 64),
            ("kind", self.kind, MAX_EVIDENCE_KIND_LENGTH),
            ("provenance", self.provenance, MAX_PROVENANCE_LENGTH),
        ):
            if not value or len(value) > maximum:
                raise ValueError(f"{field_name} must contain between 1 and {maximum} characters")
        if self.interval_start_us < 0 or self.interval_end_us < self.interval_start_us:
            raise ValueError("evidence interval must be ordered and non-negative")
        if self.observed_monotonic_us < 0 or self.timing_uncertainty_us < 0:
            raise ValueError("evidence timing values must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if len(self.payload) > MAX_EVIDENCE_PAYLOAD_FIELDS:
            raise ValueError("evidence payload contains too many fields")
        object.__setattr__(self, "payload", _freeze_bounded(self.payload))
