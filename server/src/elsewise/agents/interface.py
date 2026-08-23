from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class AgentHealth:
    status: Literal["stopped", "starting", "ready", "unavailable", "error"]
    version: str | None = None
    authenticated: bool | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class AgentModelOption:
    id: str
    name: str
    description: str = ""
    reasoning_efforts: tuple[str, ...] = ()
    default_reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionConfig:
    allow_workspace_write: bool = False
    allow_network: bool = False

    def sandbox_policy(self, cwd: str) -> dict[str, Any]:
        if not self.allow_workspace_write:
            return {"type": "readOnly", "networkAccess": self.allow_network}
        return {
            "type": "workspaceWrite",
            "writableRoots": [cwd],
            "networkAccess": self.allow_network,
            "excludeSlashTmp": True,
            "excludeTmpdirEnvVar": True,
        }


@dataclass(frozen=True, slots=True)
class ThreadConfig:
    cwd: str
    permissions: PermissionConfig = field(default_factory=PermissionConfig)
    model: str | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class RunConfig:
    cwd: str
    permissions: PermissionConfig = field(default_factory=PermissionConfig)
    model: str | None = None
    reasoning_effort: str | None = None
    inactivity_timeout_seconds: float = 300.0
    total_timeout_seconds: float = 600.0


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: Literal["started", "delta", "completed", "failed", "interrupted"]
    turn_id: str | None = None
    text: str = ""
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentProvider(Protocol):
    async def health(self) -> AgentHealth: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def models(self) -> tuple[AgentModelOption, ...]: ...

    async def create_thread(self, config: ThreadConfig) -> str: ...

    async def resume_thread(self, thread_id: str, config: ThreadConfig) -> None: ...

    def run_turn(
        self, thread_id: str, input_text: str, config: RunConfig
    ) -> AsyncIterator[AgentEvent]: ...

    async def cancel_turn(self, thread_id: str, turn_id: str) -> None: ...
