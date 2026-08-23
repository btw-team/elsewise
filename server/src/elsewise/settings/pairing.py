import contextlib
import hmac
import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import cast

from elsewise.runtime.locking import FileLock

MIN_TOKEN_LENGTH = 16
MAX_TOKEN_LENGTH = 4096


@dataclass(frozen=True)
class PairingMetadata:
    masked_token: str
    created_at: str
    generation: int


class PairingManager:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def ensure(self) -> PairingMetadata:
        with self._lock, self._file_lock():
            try:
                return self._metadata_unlocked()
            except (OSError, ValueError, KeyError, TypeError):
                self._write_unlocked(secrets.token_urlsafe(32), generation=1)
            return self._metadata_unlocked()

    def regenerate(self) -> str:
        with self._lock, self._file_lock():
            token = secrets.token_urlsafe(32)
            self._write_unlocked(token, generation=self._current_generation_unlocked() + 1)
            return token

    def token(self) -> str:
        with self._lock:
            return str(self._read()["token"])

    def save(self, token: str) -> PairingMetadata:
        normalized = token.strip()
        if not MIN_TOKEN_LENGTH <= len(normalized) <= MAX_TOKEN_LENGTH:
            raise ValueError(
                f"Pairing token must contain {MIN_TOKEN_LENGTH} to {MAX_TOKEN_LENGTH} characters."
            )
        with self._lock, self._file_lock():
            try:
                if normalized == str(self._read()["token"]):
                    return self._metadata_unlocked()
            except (OSError, ValueError, KeyError, TypeError):
                pass
            self._write_unlocked(
                normalized,
                generation=self._current_generation_unlocked() + 1,
            )
            return self._metadata_unlocked()

    def verify(self, token: str) -> bool:
        with self._lock:
            if not self.path.exists():
                return False
            return hmac.compare_digest(token, str(self._read()["token"]))

    def metadata(self) -> PairingMetadata:
        with self._lock:
            return self._metadata_unlocked()

    def _metadata_unlocked(self) -> PairingMetadata:
        payload = self._read()
        token = str(payload["token"])
        if not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH:
            raise ValueError("Invalid pairing token length.")
        return PairingMetadata(
            masked_token=f"{token[:4]}…{token[-4:]}",
            created_at=str(payload["created_at"]),
            generation=int(payload["generation"]),
        )

    def _current_generation_unlocked(self) -> int:
        if self.path.exists():
            try:
                return int(self._read()["generation"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return 0

    def _write_unlocked(self, token: str, *, generation: int) -> None:
        payload = {
            "token": token,
            "created_at": datetime.now(UTC).isoformat(),
            "generation": generation,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    def _file_lock(self) -> FileLock:
        return FileLock(self.path.with_name(f".{self.path.name}.lock"))

    def _read(self) -> dict[str, str | int]:
        return cast(dict[str, str | int], json.loads(self.path.read_text(encoding="utf-8")))
