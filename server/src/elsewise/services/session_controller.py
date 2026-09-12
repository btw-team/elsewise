import asyncio

from elsewise.persistence.database import Database
from elsewise.persistence.models import SessionRecord
from elsewise.services.errors import ServiceError
from elsewise.services.sessions import SessionService
from elsewise.services.transitions import TransitionExecutor
from elsewise.sources.manager import SourceManager

SESSION_STOP_BUDGET_SECONDS = 3.0


class SessionController:
    def __init__(
        self,
        database: Database,
        sources: SourceManager,
        transitions: TransitionExecutor,
    ) -> None:
        self.sessions = SessionService(database)
        self.sources = sources
        self.transitions = transitions
        self._source_start_tasks: set[asyncio.Task[str]] = set()

    def _dispatch_source_start(self, epoch_id: str) -> None:
        task = asyncio.create_task(self.sources.start_epoch(epoch_id))
        self._source_start_tasks.add(task)
        task.add_done_callback(self._source_start_tasks.discard)

    async def close(self) -> None:
        for task in self._source_start_tasks:
            task.cancel()
        if self._source_start_tasks:
            await asyncio.gather(*self._source_start_tasks, return_exceptions=True)

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
            self.sessions.start(session_id)
            epoch = self.sources.attach_for_session(session_id)
            if epoch is not None:
                self._dispatch_source_start(epoch.id)
            return self.sessions.get(session_id)

        return await self.transitions.run(operation)

    async def select_source(self, session_id: str, source_id: str) -> SessionRecord:
        async def operation() -> SessionRecord:
            current = self.sessions.get(session_id)
            if current.recording_status != "running":
                raise ServiceError(
                    "session_not_running", "The session is not running.", status_code=409
                )
            if current.selected_source_id == source_id:
                return current
            current_epoch = self.sources.selected_epoch(session_id)
            if current_epoch is not None:
                await self.sources.finalize_epoch(current_epoch.id, reason="source_switched")
            epoch = self.sources.select(session_id, source_id)
            await self.sources.start_epoch(epoch.id)
            return self.sessions.get(session_id)

        return await self.transitions.run(operation)

    async def stop(self, session_id: str, *, reason: str = "user") -> SessionRecord:
        async def operation() -> SessionRecord:
            session = self.sessions.begin_stop(session_id)
            if session.recording_status == "stopped":
                return session
            await self.sources.finalize_session(
                session_id, hard_budget_seconds=SESSION_STOP_BUDGET_SECONDS
            )
            return self.sessions.finish_stop(session_id, reason=reason)

        return await self.transitions.run(operation)
