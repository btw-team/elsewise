import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_iso(timestamp: float | None = None) -> str:
    value = datetime.now(UTC) if timestamp is None else datetime.fromtimestamp(timestamp, UTC)
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RuntimeDescriptor:
    pid: int
    process_create_time: float
    process_started_at: str
    server_started_at: str
    version: str
    url: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RuntimeDescriptor":
        return cls(
            pid=int(value["pid"]),
            process_create_time=float(value["process_create_time"]),
            process_started_at=str(value["process_started_at"]),
            server_started_at=str(value["server_started_at"]),
            version=str(value["version"]),
            url=str(value["url"]),
        )


class RuntimeDescriptorStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RuntimeDescriptor | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return None
            return RuntimeDescriptor.from_dict(value)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, descriptor: RuntimeDescriptor) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(descriptor), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    def remove(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
