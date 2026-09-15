import asyncio
from time import monotonic
from typing import Protocol

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import SessionRecord
from elsewise.services.errors import ServiceError
from elsewise.services.sessions import SessionService
from elsewise.services.transitions import TransitionExecutor
from elsewise.sources.contracts import SourceRole
from elsewise.sources.manager import SourceManager

SESSION_STOP_BUDGET_SECONDS = 3.0


class NativeSourceRuntime(Protocol):
    async def prepare_session(self, session_id: str) -> dict[SourceRole, str]: ...

    def handles_epoch(self, epoch_id: str) -> bool: ...

    async def start_epoch(self, epoch_id: str) -> str: ...

    async def finalize_epoch(self, epoch_id: str, *, timeout_seconds: float) -> bool: ...

    async def finalize_session(self, session_id: str, *, hard_budget_seconds: float) -> None: ...

    async def close(self) -> None: ...


class SessionController:
    def __init__(
        self,
        database: Database,
        sources: SourceManager,
        transitions: TransitionExecutor,
        native_runtime: NativeSourceRuntime | None = None,
    ) -> None:
        self.sessions = SessionService(database)
        self.sources = sources
        self.transitions = transitions
        self.native_runtime = native_runtime
        self._source_start_tasks: set[asyncio.Task[str]] = set()

    def _dispatch_source_start(self, epoch_id: str) -> None:
        task = asyncio.create_task(self._start_epoch(epoch_id))
        self._source_start_tasks.add(task)
        task.add_done_callback(self._source_start_tasks.discard)

    async def _start_epoch(self, epoch_id: str) -> str:
        if self.native_runtime is not None and self.native_runtime.handles_epoch(epoch_id):
            return await self.native_runtime.start_epoch(epoch_id)
        return await self.sources.start_epoch(epoch_id)

    async def _finalize_epoch(self, epoch_id: str, *, reason: str) -> None:
        if self.native_runtime is not None and self.native_runtime.handles_epoch(epoch_id):
            await self.native_runtime.finalize_epoch(
                epoch_id, timeout_seconds=SESSION_STOP_BUDGET_SECONDS
            )
        await self.sources.finalize_epoch(epoch_id, reason=reason)

    async def close(self) -> None:
        for task in self._source_start_tasks:
            task.cancel()
        if self._source_start_tasks:
            await asyncio.gather(*self._source_start_tasks, return_exceptions=True)
        try:
            active_sessions = tuple(
                session.id
                for session in self.sessions.list_all()
                if session.recording_status in {"starting", "running", "stopping"}
            )
            for session_id in active_sessions:
                await self.stop(session_id, reason="server_shutdown")
        finally:
            if self.native_runtime is not None:
                await self.native_runtime.close()

    async def start(self, session_id: str) -> SessionRecord:
        if self.sessions.get(session_id).recording_status == "stopping":
            raise ServiceError(
                "session_transition_in_progress",
                "The session is still stopping.",
                status_code=409,
            )

        async def operation() -> SessionRecord:
            current = self.sessions.get(session_id)
            if current.recording_status == "running":
                return current
            selected_native: dict[SourceRole, str] = {}
            if self.native_runtime is not None:
                try:
                    selected_native = await self.native_runtime.prepare_session(session_id)
                except Exception as error:
                    log_event(
                        "native_audio.prepare_failed",
                        session_id=session_id,
                        error_code=type(error).__name__,
                    )
            self.sessions.start(session_id)
            epochs = [
                self.sources.select(session_id, source_id, role=str(role))
                for role, source_id in selected_native.items()
            ]
            epochs.extend(self.sources.attach_for_session(session_id))
            for epoch in {epoch.id: epoch for epoch in epochs}.values():
                self._dispatch_source_start(epoch.id)
            return self.sessions.get(session_id)

        return await self.transitions.run(operation)

    async def select_source(self, session_id: str, source_id: str, *, role: str) -> SessionRecord:
        async def operation() -> SessionRecord:
            current = self.sessions.get(session_id)
            if current.recording_status != "running":
                raise ServiceError(
                    "session_not_running", "The session is not running.", status_code=409
                )
            current_epoch = self.sources.selected_epoch(session_id, role=role)
            if current_epoch is not None and current_epoch.source_id == source_id:
                return current
            if current_epoch is not None:
                await self._finalize_epoch(current_epoch.id, reason="source_switched")
            epoch = self.sources.select(session_id, source_id, role=role)
            await self._start_epoch(epoch.id)
            return self.sessions.get(session_id)

        return await self.transitions.run(operation)

    async def stop(self, session_id: str, *, reason: str = "user") -> SessionRecord:
        async def operation() -> SessionRecord:
            session = self.sessions.begin_stop(session_id)
            if session.recording_status == "stopped":
                return session
            started = monotonic()
            if self.native_runtime is not None:
                await self.native_runtime.finalize_session(
                    session_id, hard_budget_seconds=SESSION_STOP_BUDGET_SECONDS
                )
            remaining = max(0.01, SESSION_STOP_BUDGET_SECONDS - (monotonic() - started))
            await self.sources.finalize_session(session_id, hard_budget_seconds=remaining)
            return self.sessions.finish_stop(session_id, reason=reason)

        return await self.transitions.run(operation)
