from dataclasses import dataclass
from enum import StrEnum


class SourceCategory(StrEnum):
    AUDIO = "audio"
    CAPTIONS = "captions"
    SEMANTIC = "semantic"
    SYNTHETIC = "synthetic"


class SourceRole(StrEnum):
    SELF = "self"
    REMOTE = "remote"
    SECONDARY = "secondary"


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    id: str
    kind: str
    category: SourceCategory
    platform: str
    driver_id: str
    driver_version: str
    protocol_version: int
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        bounded = {
            "id": (self.id, 256),
            "kind": (self.kind, 64),
            "platform": (self.platform, 64),
            "driver_id": (self.driver_id, 128),
            "driver_version": (self.driver_version, 64),
        }
        for field_name, (value, maximum) in bounded.items():
            if not value or len(value) > maximum:
                raise ValueError(f"{field_name} must contain between 1 and {maximum} characters")
        if self.protocol_version < 1:
            raise ValueError("protocol_version must be positive")
        if len(self.capabilities) > 32 or any(
            not capability or len(capability) > 64 for capability in self.capabilities
        ):
            raise ValueError("capabilities must contain at most 32 bounded values")
