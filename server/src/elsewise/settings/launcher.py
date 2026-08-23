from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from elsewise.runtime.locking import FileLock
from elsewise.settings.json_store import RecoverableJsonFile, RecoveryNotice


class LauncherSettings(BaseModel):
    start_server_on_launch: bool = True
    check_updates_on_launch: bool = True
    stop_server_on_exit: bool = False
    server_log_total_limit_mb: int = Field(default=50)

    @classmethod
    def supported_log_limits(cls) -> tuple[int, ...]:
        return (10, 25, 50, 100, 250)

    def validate_log_limit(self) -> "LauncherSettings":
        if self.server_log_total_limit_mb not in self.supported_log_limits():
            raise ValueError("Unsupported server log limit")
        return self


@dataclass(slots=True)
class LauncherSettingsStore:
    path: Path
    recovery_notice: RecoveryNotice | None = None

    def load(self) -> LauncherSettings:
        with FileLock(self.path.with_name(f".{self.path.name}.lock")):
            file = self._file()
            result = file.load()
            self.recovery_notice = file.recovery_notice or self.recovery_notice
            return result

    def save(self, settings: LauncherSettings) -> None:
        settings.validate_log_limit()
        with FileLock(self.path.with_name(f".{self.path.name}.lock")):
            self._file().save(settings)

    def update(self, **changes: object) -> LauncherSettings:
        candidate = self.load().model_copy(update=changes)
        validated = LauncherSettings.model_validate(candidate.model_dump()).validate_log_limit()
        self.save(validated)
        return validated

    def _file(self) -> RecoverableJsonFile[LauncherSettings]:
        def parse(payload: str) -> LauncherSettings:
            return LauncherSettings.model_validate_json(payload).validate_log_limit()

        return RecoverableJsonFile(
            self.path,
            parse=parse,
            serialize=lambda value: value.model_dump_json(indent=2),
            default=LauncherSettings,
        )
