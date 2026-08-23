import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs


@dataclass(frozen=True, slots=True)
class AppPaths:
    data: Path
    config: Path
    cache: Path
    runtime: Path
    database: Path
    exports: Path
    diagnostics: Path
    agent_empty_cwd: Path

    _ENV_NAMES = {
        "data": "ELSEWISE_DATA_DIR",
        "config": "ELSEWISE_CONFIG_DIR",
        "cache": "ELSEWISE_CACHE_DIR",
        "runtime": "ELSEWISE_RUNTIME_DIR",
        "diagnostics": "ELSEWISE_DIAGNOSTICS_DIR",
    }

    @classmethod
    def resolve(cls, *, ensure_exists: bool = False) -> "AppPaths":
        dirs = PlatformDirs("Elsewise", appauthor=False, ensure_exists=ensure_exists)
        data = Path(os.environ.get(cls._ENV_NAMES["data"], dirs.user_data_path))
        config = Path(os.environ.get(cls._ENV_NAMES["config"], dirs.user_config_path))
        cache = Path(os.environ.get(cls._ENV_NAMES["cache"], dirs.user_cache_path))
        runtime = Path(os.environ.get(cls._ENV_NAMES["runtime"], data / "runtime"))
        diagnostics = Path(os.environ.get(cls._ENV_NAMES["diagnostics"], data / "diagnostics"))
        paths = cls(
            data=data,
            config=config,
            cache=cache,
            runtime=runtime,
            database=data / "elsewise.sqlite3",
            exports=data / "exports",
            diagnostics=diagnostics,
            agent_empty_cwd=runtime / "agent-empty-cwd",
        )
        if ensure_exists:
            for directory in (
                paths.data,
                paths.config,
                paths.cache,
                paths.runtime,
                paths.exports,
                paths.diagnostics,
                paths.agent_empty_cwd,
            ):
                directory.mkdir(parents=True, exist_ok=True)
        return paths

    def environment(self) -> dict[str, str]:
        return {
            self._ENV_NAMES["data"]: str(self.data),
            self._ENV_NAMES["config"]: str(self.config),
            self._ENV_NAMES["cache"]: str(self.cache),
            self._ENV_NAMES["runtime"]: str(self.runtime),
            self._ENV_NAMES["diagnostics"]: str(self.diagnostics),
        }
