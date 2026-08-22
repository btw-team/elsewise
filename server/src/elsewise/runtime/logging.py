import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import Any

_FORMAT = "%(asctime)s %(levelname)s %(name)s pid=%(process)d %(message)s"


class ParticipantNameRedactor(logging.Filter):
    """Replace registered participant names with session-scoped aliases."""

    def __init__(self) -> None:
        super().__init__()
        self._aliases: dict[str, dict[str, str]] = {}
        self._lock = RLock()

    def register(self, session_id: str, participant_name: str) -> str:
        normalized = participant_name.strip()
        if not normalized:
            return ""
        with self._lock:
            session_aliases = self._aliases.setdefault(session_id, {})
            alias = session_aliases.get(normalized)
            if alias is None:
                alias = f"Participant {len(session_aliases) + 1}"
                session_aliases[normalized] = alias
            return alias

    def forget_session(self, session_id: str) -> None:
        with self._lock:
            self._aliases.pop(session_id, None)

    def redact(self, value: str) -> str:
        with self._lock:
            replacements = tuple(
                (name, alias)
                for session_aliases in self._aliases.values()
                for name, alias in session_aliases.items()
            )
        result = value
        for name, alias in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            result = result.replace(name, alias)
        return result

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact_value(record.msg)
        if record.args:
            record.args = self._redact_value(record.args)
        return True

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        if isinstance(value, dict):
            return {key: self._redact_value(item) for key, item in value.items()}
        return value


participant_name_redactor = ParticipantNameRedactor()


def configure_server_logging(diagnostics: Path, total_limit_mb: int = 50) -> Path:
    diagnostics.mkdir(parents=True, exist_ok=True)
    log_path = diagnostics / "server.log"
    max_bytes = max(1, total_limit_mb) * 1024 * 1024 // 5
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=4,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(participant_name_redactor)
    root = logging.getLogger()
    for existing in tuple(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    return log_path


def configure_launcher_logging(diagnostics: Path) -> Path:
    diagnostics.mkdir(parents=True, exist_ok=True)
    log_path = diagnostics / "launcher.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger = logging.getLogger("elsewise.launcher")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return log_path
