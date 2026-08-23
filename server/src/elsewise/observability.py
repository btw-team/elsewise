import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any

_LOGGER = logging.getLogger("elsewise.events")
_SAFE_FIELDS = frozenset(
    {
        "authenticated",
        "error_type",
        "file_count",
        "path",
        "platform",
        "queue_size",
        "reason",
        "recoverable",
        "result",
        "run_id",
        "session_id",
        "source_id",
        "state",
        "status",
    }
)


def log_event(event: str, **fields: Any) -> None:
    """Emit a compact JSON event containing identifiers and counters, never content."""
    payload: dict[str, str | int | bool | None] = {"event": event}
    for key, value in fields.items():
        if key not in _SAFE_FIELDS:
            raise ValueError(f"Unsafe structured log field: {key}")
        if isinstance(value, Path):
            payload[key] = str(value)
        elif value is None or isinstance(value, (str, int, bool)):
            payload[key] = value
        else:
            payload[key] = str(value)
    _LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))


class RuntimeDiagnostics:
    def __init__(self) -> None:
        self._lock = RLock()
        self._values = {
            "ingest_connections_total": 0,
            "ingest_clients_connected": 0,
            "ingest_disconnects_total": 0,
            "ui_connections_total": 0,
            "ui_clients_connected": 0,
            "ui_disconnects_total": 0,
            "launcher_connections_total": 0,
            "launcher_clients_connected": 0,
            "launcher_disconnects_total": 0,
        }

    def connected(self, role: str) -> None:
        with self._lock:
            self._values[f"{role}_connections_total"] += 1
            self._values[f"{role}_clients_connected"] += 1

    def disconnected(self, role: str) -> None:
        with self._lock:
            key = f"{role}_clients_connected"
            self._values[key] = max(0, self._values[key] - 1)
            self._values[f"{role}_disconnects_total"] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)
