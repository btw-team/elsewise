import contextlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecoveryNotice:
    file_name: str
    source: str


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            if not payload.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


class RecoverableJsonFile[T]:
    def __init__(
        self,
        path: Path,
        *,
        parse: Callable[[str], T],
        serialize: Callable[[T], str],
        default: Callable[[], T],
    ) -> None:
        self.path = path
        self.backup_path = path.with_name(f"{path.name}.bak")
        self.parse = parse
        self.serialize = serialize
        self.default = default
        self.recovery_notice: RecoveryNotice | None = None

    def _read_valid(self, path: Path) -> T | None:
        try:
            return self.parse(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def load(self) -> T:
        primary_exists = self.path.exists()
        primary = self._read_valid(self.path) if primary_exists else None
        if primary is not None:
            return primary
        backup = self._read_valid(self.backup_path)
        if backup is not None:
            _atomic_write(self.path, self.serialize(backup))
            self.recovery_notice = RecoveryNotice(self.path.name, "backup")
            return backup
        fallback = self.default()
        if primary_exists:
            payload = self.serialize(fallback)
            _atomic_write(self.path, payload)
            _atomic_write(self.backup_path, payload)
            self.recovery_notice = RecoveryNotice(self.path.name, "defaults")
        return fallback

    def save(self, value: T) -> None:
        payload = self.serialize(value)
        current = self._read_valid(self.path)
        if current is not None:
            _atomic_write(self.backup_path, self.serialize(current))
        _atomic_write(self.path, payload)
        if self._read_valid(self.backup_path) is None:
            _atomic_write(self.backup_path, payload)
