import asyncio
import contextlib
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from elsewise import __version__
from elsewise.agents.interface import AgentHealth
from elsewise.agents.queue import AgentQueueManager
from elsewise.observability import RuntimeDiagnostics
from elsewise.persistence.database import Database
from elsewise.persistence.models import AgentRunRecord, CaptureSourceRecord, SessionRecord
from elsewise.runtime.descriptor import RuntimeDescriptorStore
from elsewise.settings.config import SettingsStore
from elsewise.settings.paths import AppPaths


def _known_executable_candidates(command: str) -> tuple[Path, ...]:
    executable = f"{command}.exe" if os.name == "nt" and not command.endswith(".exe") else command
    windows_shim = f"{command}.cmd" if os.name == "nt" and not command.endswith(".cmd") else command
    home = Path.home()
    candidates = [home / ".local" / "bin" / executable]
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        local_app_data = os.environ.get("LOCALAPPDATA")
        if app_data:
            candidates.append(Path(app_data) / "npm" / windows_shim)
        if local_app_data:
            candidates.extend(
                (
                    Path(local_app_data) / "Programs" / executable,
                    Path(local_app_data) / executable,
                )
            )
    else:
        candidates.extend(
            (
                Path("/usr/local/bin") / executable,
                Path("/opt/homebrew/bin") / executable,
                Path("/snap/bin") / executable,
            )
        )
    return tuple(candidates)


def resolve_executable(command: str) -> str | None:
    expanded = Path(command).expanduser()
    if expanded.is_absolute() or expanded.parent != Path("."):
        try:
            resolved = expanded.resolve(strict=True)
            return str(resolved) if resolved.is_file() else None
        except OSError:
            return None
    discovered = shutil.which(command)
    if discovered:
        return str(Path(discovered).resolve())
    for candidate in _known_executable_candidates(command):
        if candidate.is_file():
            return str(candidate.resolve())
    return None


class RuntimeStatusService:
    def __init__(
        self,
        database: Database,
        diagnostics: RuntimeDiagnostics,
        manager: AgentQueueManager,
        settings: SettingsStore,
        paths: AppPaths,
        *,
        agent_refresh_seconds: float = 30.0,
    ) -> None:
        self.database = database
        self.diagnostics = diagnostics
        self.manager = manager
        self.settings = settings
        self.paths = paths
        self.agent_refresh_seconds = agent_refresh_seconds
        self.created_at = datetime.now(UTC)
        self._agent_health: dict[str, AgentHealth] = {}
        self._agent_refreshed_at = 0.0
        self._refresh_task: asyncio.Task[None] | None = None

    async def stop(self) -> None:
        task = self._refresh_task
        self._refresh_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def snapshot(self) -> dict[str, Any]:
        self._schedule_agent_refresh()
        if not self._agent_health:
            self._agent_health = {
                provider_id: await self.manager.providers.get(provider_id).health()
                for provider_id in self.manager.providers.ids
            }
        configured = self.settings.load()
        descriptor = RuntimeDescriptorStore(self.paths.runtime / "server.json").load()
        started_at = self.created_at
        pid = os.getpid()
        if descriptor is not None and descriptor.pid == pid and descriptor.server_started_at:
            with contextlib.suppress(ValueError):
                started_at = datetime.fromisoformat(
                    descriptor.server_started_at.replace("Z", "+00:00")
                )
        now = datetime.now(UTC)
        diagnostics = self.diagnostics.snapshot()
        with self.database.transaction() as db:
            session = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running").limit(1)
            )
            source = None
            if session is not None and session.active_source_id:
                source = db.get(CaptureSourceRecord, session.active_source_id)
            run_counts = {
                status: int(count)
                for status, count in db.execute(
                    select(AgentRunRecord.status, func.count(AgentRunRecord.id))
                    .where(AgentRunRecord.status.in_(("queued", "starting", "streaming")))
                    .group_by(AgentRunRecord.status)
                ).tuples()
            }
        commands = {
            "codex": configured.codex_executable,
            "claude": configured.claude_executable,
        }
        return {
            "server": {
                "status": "running",
                "pid": pid,
                "version": __version__,
                "started_at": started_at.isoformat(),
                "uptime_seconds": max(0.0, (now - started_at).total_seconds()),
                "url": "http://127.0.0.1:38473",
            },
            "connections": {
                "web_gui": {
                    "connected": diagnostics["ui_clients_connected"] > 0,
                    "count": diagnostics["ui_clients_connected"],
                },
                "browser_extension": {
                    "connected": diagnostics["ingest_clients_connected"] > 0,
                    "count": diagnostics["ingest_clients_connected"],
                },
            },
            "session": (
                {
                    "id": session.id,
                    "title": session.title,
                    "recording_status": session.recording_status,
                    "capture_status": session.capture_status,
                }
                if session is not None
                else None
            ),
            "source": (
                {
                    "platform": source.platform,
                    "captions_status": source.captions_status,
                    "connected": source.connected,
                }
                if source is not None
                else None
            ),
            "agent_work": {
                "queued": run_counts.get("queued", 0),
                "running": run_counts.get("starting", 0) + run_counts.get("streaming", 0),
                "draining": self.manager.draining,
            },
            "settings": {
                "ui_language": configured.ui_language,
                "ui_theme": configured.ui_theme,
            },
            "agents": {
                provider_id: {
                    "id": provider_id,
                    "name": "Claude Code" if provider_id == "claude" else "Codex",
                    "status": health.status,
                    "version": health.version,
                    "authenticated": health.authenticated,
                    "message": health.message,
                    "configured_command": commands.get(provider_id, provider_id),
                    "resolved_executable": resolve_executable(
                        commands.get(provider_id, provider_id)
                    ),
                }
                for provider_id, health in self._agent_health.items()
            },
        }

    def _schedule_agent_refresh(self) -> None:
        now = time.monotonic()
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        if now - self._agent_refreshed_at < self.agent_refresh_seconds:
            return
        self._refresh_task = asyncio.create_task(
            self._refresh_agents(), name="elsewise-runtime-agent-health"
        )

    async def _refresh_agents(self) -> None:
        try:
            self._agent_health = await self.manager.health_all(refresh=True)
            self._agent_refreshed_at = time.monotonic()
        except Exception:
            # Individual providers retain their typed health state; the next
            # scheduled refresh will retry without breaking runtime status.
            self._agent_health = {
                provider_id: await self.manager.providers.get(provider_id).health()
                for provider_id in self.manager.providers.ids
            }
