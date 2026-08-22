import asyncio
import contextlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from elsewise.agents.context_repository import AgentContextRepository
from elsewise.agents.interface import (
    AgentHealth,
    AgentModelOption,
    AgentProvider,
    PermissionConfig,
    RunConfig,
    ThreadConfig,
)
from elsewise.agents.prompts import (
    ContextStrategy,
    action_prompt,
    freeze_context,
    initial_prompt,
)
from elsewise.agents.registry import AgentProviderRegistry
from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    AgentMessageRecord,
    AgentRunRecord,
    AgentThreadRecord,
    ButtonDefinitionRecord,
    SessionRecord,
    utc_now,
)
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event
from elsewise.settings.config import SettingsStore
from elsewise.settings.limits import (
    MAX_AGENT_OUTPUT_CHARACTERS,
    MAX_QUEUED_AGENT_RUNS_PER_SESSION,
)
from elsewise.settings.paths import AppPaths

AGENT_INACTIVITY_TIMEOUT_SECONDS = 5 * 60.0
AGENT_TURN_TIMEOUT_SECONDS = 10 * 60.0
AGENT_INITIAL_TIMEOUT_SECONDS = 15 * 60.0


class AgentTotalTimeoutError(TimeoutError):
    pass


def resolve_session_cwd(requested: str | None, fallback: Path) -> tuple[str, bool]:
    fallback.mkdir(parents=True, exist_ok=True)
    if requested:
        try:
            candidate = Path(requested).expanduser().resolve(strict=True)
            if candidate.is_dir():
                return str(candidate), False
        except (OSError, RuntimeError):
            pass
    return str(fallback.resolve(strict=True)), True


def run_payload(run: AgentRunRecord) -> dict[str, Any]:
    return {
        "id": run.id,
        "session_id": run.session_id,
        "thread_id": run.thread_id,
        "button_id": run.button_id,
        "queue_sequence": run.queue_sequence,
        "status": run.status,
        "button_snapshot": run.button_snapshot,
        "resolved_prompt": run.resolved_prompt,
        "frozen_context": run.frozen_context,
        "context_strategy": run.context_strategy,
        "context_start": run.context_start,
        "context_end": run.context_end,
        "session_language": run.session_language,
        "provider": run.provider,
        "model": run.model,
        "reasoning_effort": run.reasoning_effort,
        "cwd": run.cwd,
        "permissions_snapshot": run.permissions_snapshot,
        "external_turn_id": run.external_turn_id,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_type": run.error_type,
        "error_message": run.error_message,
    }


def message_payload(message: AgentMessageRecord) -> dict[str, Any]:
    return {
        "id": message.id,
        "run_id": message.run_id,
        "role": message.role,
        "message_type": message.message_type,
        "text": message.text,
        "sequence": message.sequence,
        "status": message.status,
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat(),
    }


class AgentQueueManager:
    def __init__(
        self,
        database: Database,
        provider: AgentProvider | AgentProviderRegistry,
        paths: AppPaths,
        settings: SettingsStore,
        *,
        poll_interval: float = 0.1,
    ) -> None:
        self.database = database
        self.providers = (
            provider
            if isinstance(provider, AgentProviderRegistry)
            else AgentProviderRegistry({"codex": provider})
        )
        self.paths = paths
        self.settings = settings
        self.poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._draining = False
        self._active_run_id: str | None = None
        self._resumed_threads: set[tuple[str, str]] = set()
        self._provider_reconfigure_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._worker(), name="elsewise-agent-queue")

    @property
    def draining(self) -> bool:
        return self._draining

    def set_draining(self, enabled: bool) -> None:
        self._draining = enabled

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
        try:
            # Stopping the provider releases any in-flight I/O that the worker may
            # be awaiting while it handles cancellation. Waiting for the worker
            # first can deadlock shutdown when that cleanup depends on the provider.
            await self.providers.stop()
        finally:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def health(self, provider_id: str) -> AgentHealth:
        return await self.providers.health(provider_id)

    async def health_all(self, *, refresh: bool = False) -> dict[str, AgentHealth]:
        return await self.providers.health_all(refresh=refresh)

    async def models(self, provider_id: str) -> tuple[AgentModelOption, ...]:
        return await self.providers.models(provider_id)

    async def models_all(self) -> dict[str, tuple[AgentModelOption, ...]]:
        return await self.providers.models_all()

    async def replace_provider(self, provider_id: str, provider: AgentProvider) -> AgentProvider:
        async with self._provider_reconfigure_lock:
            with self.database.transaction() as db:
                busy = db.scalar(
                    select(func.count(AgentRunRecord.id)).where(
                        AgentRunRecord.provider == provider_id,
                        AgentRunRecord.status.in_(("queued", "starting", "streaming")),
                    )
                )
            if busy:
                raise ServiceError(
                    "agent_provider_busy",
                    "Stop or finish queued agent work before changing this executable.",
                    status_code=409,
                )
            previous = await self.providers.replace(provider_id, provider)
            previous_cache = set(self._resumed_threads)
            try:
                self._resumed_threads = {
                    key for key in self._resumed_threads if key[0] != provider_id
                }
                await self.providers.health(provider_id, refresh=True)
            except Exception:
                with contextlib.suppress(Exception):
                    await self.providers.replace(provider_id, previous)
                self._resumed_threads = previous_cache
                raise
            return previous

    def ensure_initial_run(self, session_id: str) -> AgentRunRecord | None:
        if self._draining:
            raise ServiceError(
                "agent_queue_draining",
                "New agent work is paused while Elsewise prepares to restart.",
                status_code=409,
            )
        configured = self.settings.load()
        with self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            if session is None:
                raise ServiceError("session_not_found", "Session not found.", status_code=404)
            existing = db.scalar(
                select(AgentThreadRecord).where(AgentThreadRecord.session_id == session_id)
            )
            if existing is not None:
                return None
            cwd, fallback = resolve_session_cwd(
                session.requested_agent_cwd, self.paths.agent_empty_cwd
            )
            session.resolved_agent_cwd = cwd
            session.agent_cwd_fallback = fallback
            session.agent_status = "starting"
            configured_prompt = session.initial_prompt or configured.initial_prompts.get(
                session.language,
                configured.initial_prompts.get(session.language.split("-")[0], ""),
            )
            prompt = initial_prompt(
                language=session.language,
                configured_prompt=configured_prompt,
                cwd=cwd,
                writable=session.allow_workspace_write,
            )
            thread = AgentThreadRecord(
                session_id=session.id,
                provider=session.agent_provider,
                init_prompt_version=configured.initial_prompt_version,
                init_prompt_snapshot=prompt,
                status="starting",
            )
            db.add(thread)
            db.flush()
            run = AgentRunRecord(
                session_id=session.id,
                thread_id=thread.id,
                queue_sequence=1,
                status="queued",
                button_snapshot={"kind": "initial", "version": configured.initial_prompt_version},
                resolved_prompt=prompt,
                frozen_context="",
                context_strategy="initial",
                session_language=session.language,
                provider=session.agent_provider,
                model=session.agent_model,
                reasoning_effort=session.agent_reasoning_effort,
                cwd=cwd,
                permissions_snapshot={
                    "allow_workspace_write": session.allow_workspace_write,
                    "allow_network": session.allow_network,
                },
            )
            db.add(run)
            db.flush()
            emit_ui_event(db, "agent.queued", run.id, run_payload(run))
            log_event("agent.queued", session_id=session.id, run_id=run.id, queue_size=1)
            return run

    def enqueue_action(self, session_id: str, button_id: str) -> AgentRunRecord:
        with self.database.transaction() as db:
            session, thread, queued_count = self._prepare_run(db, session_id)
            button = db.get(ButtonDefinitionRecord, button_id)
            if button is None or not button.enabled:
                raise ServiceError("button_not_found", "Action button not found.", status_code=404)
            return self._enqueue_prepared(
                db,
                session,
                thread,
                queued_count,
                button_id=button.id,
                button_snapshot={
                    "id": button.id,
                    "key": button.key,
                    "label": button.label,
                    "prompt_template": button.prompt_template,
                    "context_strategy": button.context_strategy,
                    "context_value": button.context_value,
                    "hard_character_cap": button.hard_character_cap,
                    "definition_version": button.definition_version,
                },
                action=button.prompt_template,
                context_strategy=cast(ContextStrategy, button.context_strategy),
                context_value=button.context_value,
                hard_character_cap=button.hard_character_cap,
            )

    def enqueue_prompt(self, session_id: str, prompt: str) -> AgentRunRecord:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ServiceError("prompt_empty", "Prompt must not be blank.", status_code=422)
        configured = self.settings.load()
        with self.database.transaction() as db:
            session, thread, queued_count = self._prepare_run(db, session_id)
            return self._enqueue_prepared(
                db,
                session,
                thread,
                queued_count,
                button_id=None,
                button_snapshot={
                    "kind": "freeform",
                    "label": normalized_prompt[:128],
                    "context_strategy": configured.free_prompt_context_strategy,
                    "context_value": configured.free_prompt_context_value,
                    "hard_character_cap": configured.free_prompt_hard_character_cap,
                },
                action=normalized_prompt,
                context_strategy=configured.free_prompt_context_strategy,
                context_value=configured.free_prompt_context_value,
                hard_character_cap=configured.free_prompt_hard_character_cap,
            )

    def _prepare_run(
        self, db: OrmSession, session_id: str
    ) -> tuple[SessionRecord, AgentThreadRecord, int]:
        if self._draining:
            raise ServiceError(
                "agent_queue_draining",
                "New agent work is paused while Elsewise prepares to restart.",
                status_code=409,
            )
        session = db.get(SessionRecord, session_id)
        if session is None:
            raise ServiceError("session_not_found", "Session not found.", status_code=404)
        thread = db.scalar(
            select(AgentThreadRecord).where(AgentThreadRecord.session_id == session_id)
        )
        if thread is None:
            raise ServiceError(
                "agent_not_started", "Start the session before running an agent action."
            )
        queued_count = db.scalar(
            select(func.count(AgentRunRecord.id)).where(
                AgentRunRecord.session_id == session_id,
                AgentRunRecord.status.in_(("queued", "starting", "streaming")),
            )
        )
        if (queued_count or 0) >= MAX_QUEUED_AGENT_RUNS_PER_SESSION:
            raise ServiceError("agent_queue_full", "The agent queue is full.", status_code=429)
        return session, thread, queued_count or 0

    def _enqueue_prepared(
        self,
        db: OrmSession,
        session: SessionRecord,
        thread: AgentThreadRecord,
        queued_count: int,
        *,
        button_id: str | None,
        button_snapshot: dict[str, Any],
        action: str,
        context_strategy: ContextStrategy,
        context_value: int | None,
        hard_character_cap: int,
    ) -> AgentRunRecord:
        selection = AgentContextRepository(db, self.settings.load()).select(
            session_id=session.id,
            thread=thread,
            strategy=context_strategy,
            value=context_value,
            hard_character_cap=hard_character_cap,
        )
        context = freeze_context(
            selection.utterances,
            strategy=context_strategy,
            value=context_value,
            hard_character_cap=hard_character_cap,
            previous_boundary_id=thread.last_completed_boundary,
            speaker_roles=selection.speaker_roles,
        )
        if selection.truncated and not context.truncated:
            context = replace(context, truncated=True)
        next_sequence = (
            db.scalar(
                select(func.max(AgentRunRecord.queue_sequence)).where(
                    AgentRunRecord.session_id == session.id
                )
            )
            or 0
        ) + 1
        run = AgentRunRecord(
            session_id=session.id,
            thread_id=thread.id,
            button_id=button_id,
            queue_sequence=next_sequence,
            status="queued",
            button_snapshot={
                **button_snapshot,
                "context_truncated": context.truncated,
                "context_start_at": context.start_at.isoformat() if context.start_at else None,
                "context_end_at": context.end_at.isoformat() if context.end_at else None,
            },
            resolved_prompt="",
            frozen_context=context.text,
            context_strategy=context_strategy,
            context_start=context.start_id,
            context_end=context.end_id,
            session_language=session.language,
            provider=thread.provider,
            model=session.agent_model,
            reasoning_effort=session.agent_reasoning_effort,
            cwd=session.resolved_agent_cwd or str(self.paths.agent_empty_cwd.resolve(strict=True)),
            permissions_snapshot={
                "allow_workspace_write": session.allow_workspace_write,
                "allow_network": session.allow_network,
            },
        )
        db.add(run)
        db.flush()
        run.resolved_prompt = action_prompt(
            language=session.language,
            action=action,
            context=context,
            run_id=run.id,
        )
        emit_ui_event(db, "agent.queued", run.id, run_payload(run))
        log_event(
            "agent.queued",
            session_id=session.id,
            run_id=run.id,
            queue_size=queued_count + 1,
        )
        return run

    async def cancel(self, run_id: str) -> AgentRunRecord:
        external_thread_id: str | None = None
        external_turn_id: str | None = None
        provider_id: str | None = None
        with self.database.transaction() as db:
            run = db.get(AgentRunRecord, run_id)
            if run is None:
                raise ServiceError("agent_run_not_found", "Agent run not found.", status_code=404)
            if run.status == "queued":
                run.status = "cancelled"
                run.completed_at = utc_now()
                emit_ui_event(db, "agent.cancelled", run.id, run_payload(run))
                log_event("agent.cancelled", run_id=run.id, state="cancelled")
                return run
            if run.status not in {"starting", "streaming"}:
                return run
            thread = db.get(AgentThreadRecord, run.thread_id)
            external_thread_id = thread.external_thread_id if thread else None
            external_turn_id = run.external_turn_id
            provider_id = thread.provider if thread else run.provider
        if provider_id and external_thread_id and external_turn_id:
            await self.providers.get(provider_id).cancel_turn(external_thread_id, external_turn_id)
        with self.database.transaction() as db:
            run = db.get(AgentRunRecord, run_id)
            assert run is not None
            if run.status in {"starting", "streaming"}:
                run.status = "cancelled"
                run.completed_at = utc_now()
                emit_ui_event(db, "agent.cancelled", run.id, run_payload(run))
                log_event("agent.cancelled", run_id=run.id, state="cancelled")
            return run

    def list_runs(self, session_id: str) -> list[AgentRunRecord]:
        with self.database.transaction() as db:
            return list(
                db.scalars(
                    select(AgentRunRecord)
                    .where(AgentRunRecord.session_id == session_id)
                    .order_by(AgentRunRecord.queue_sequence)
                )
            )

    def refresh_session_cwd(self, session_id: str) -> None:
        with self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            if session is None:
                raise ServiceError("session_not_found", "Session not found.", status_code=404)
            cwd, fallback = resolve_session_cwd(
                session.requested_agent_cwd, self.paths.agent_empty_cwd
            )
            session.resolved_agent_cwd = cwd
            session.agent_cwd_fallback = fallback

    async def _worker(self) -> None:
        while not self._stopping:
            run_id = self._next_queued_run()
            if run_id is None:
                await asyncio.sleep(self.poll_interval)
                continue
            self._active_run_id = run_id
            try:
                total_timeout = self._total_timeout_for_run(run_id)
                try:
                    async with asyncio.timeout(total_timeout):
                        await self._process_run(run_id, total_timeout=total_timeout)
                except TimeoutError:
                    await self._cancel_timed_out_run(run_id)
                    self._fail_run(
                        run_id,
                        AgentTotalTimeoutError(
                            f"Agent turn exceeded the {int(total_timeout)} second total timeout."
                        ),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._fail_run(run_id, exc)
            finally:
                self._active_run_id = None

    def _total_timeout_for_run(self, run_id: str) -> float:
        with self.database.transaction() as db:
            run = db.get(AgentRunRecord, run_id)
            return (
                AGENT_INITIAL_TIMEOUT_SECONDS
                if run is not None and run.context_strategy == "initial"
                else AGENT_TURN_TIMEOUT_SECONDS
            )

    async def _cancel_timed_out_run(self, run_id: str) -> None:
        with self.database.transaction() as db:
            run = db.get(AgentRunRecord, run_id)
            if run is None:
                return
            thread = db.get(AgentThreadRecord, run.thread_id)
            provider_id = thread.provider if thread is not None else run.provider
            thread_id = thread.external_thread_id if thread is not None else None
            turn_id = run.external_turn_id
        if thread_id and turn_id:
            with contextlib.suppress(Exception):
                await self.providers.get(provider_id).cancel_turn(thread_id, turn_id)

    def _next_queued_run(self) -> str | None:
        with self.database.transaction() as db:
            return db.scalar(
                select(AgentRunRecord.id)
                .where(AgentRunRecord.status == "queued")
                .order_by(AgentRunRecord.created_at, AgentRunRecord.queue_sequence)
                .limit(1)
            )

    async def _ensure_provider_ready(self, provider_id: str) -> AgentProvider:
        provider = self.providers.get(provider_id)
        health = await provider.health()
        if health.status != "ready":
            await provider.start()
            self._resumed_threads = {key for key in self._resumed_threads if key[0] != provider_id}
        health = await provider.health()
        if health.status != "ready":
            raise RuntimeError(health.message or "Agent provider is unavailable.")
        return provider

    async def _process_run(self, run_id: str, *, total_timeout: float) -> None:
        with self.database.transaction() as db:
            run = db.get(AgentRunRecord, run_id)
            if run is None or run.status != "queued":
                return
            run.status = "starting"
            run.started_at = utc_now()
            thread = db.get(AgentThreadRecord, run.thread_id)
            session = db.get(SessionRecord, run.session_id)
            assert thread is not None and session is not None
            provider_id = thread.provider
            session.agent_status = "starting"
            emit_ui_event(db, "agent.started", run.id, run_payload(run))
            log_event("agent.started", session_id=run.session_id, run_id=run.id, state="starting")
            external_thread_id = thread.external_thread_id
            permissions = PermissionConfig(
                allow_workspace_write=bool(
                    run.permissions_snapshot.get("allow_workspace_write", False)
                ),
                allow_network=bool(run.permissions_snapshot.get("allow_network", False)),
            )
            thread_config = ThreadConfig(
                cwd=run.cwd,
                permissions=permissions,
                model=run.model,
                reasoning_effort=run.reasoning_effort,
            )
            prompt = run.resolved_prompt

        provider = await self._ensure_provider_ready(provider_id)
        resumed_key = (provider_id, external_thread_id) if external_thread_id else None
        persist_thread_after_first_turn = False
        if external_thread_id is None:
            external_thread_id = await provider.create_thread(thread_config)
            persist_thread_after_first_turn = provider_id == "claude"
            if not persist_thread_after_first_turn:
                with self.database.transaction() as db:
                    thread = db.get(AgentThreadRecord, run.thread_id)
                    assert thread is not None
                    thread.external_thread_id = external_thread_id
                    thread.status = "ready"
                    emit_ui_event(
                        db,
                        "agent.thread",
                        thread.id,
                        {
                            "id": thread.id,
                            "external_thread_id": external_thread_id,
                            "status": "ready",
                        },
                    )
            self._resumed_threads.add((provider_id, external_thread_id))
        elif resumed_key not in self._resumed_threads:
            await provider.resume_thread(external_thread_id, thread_config)
            self._resumed_threads.add((provider_id, external_thread_id))
            with self.database.transaction() as db:
                thread = db.get(AgentThreadRecord, run.thread_id)
                assert thread is not None
                thread.resumed_at = utc_now()

        run_config = RunConfig(
            cwd=run.cwd,
            permissions=permissions,
            model=run.model,
            reasoning_effort=run.reasoning_effort,
            inactivity_timeout_seconds=AGENT_INACTIVITY_TIMEOUT_SECONDS,
            total_timeout_seconds=total_timeout,
        )
        async for event in provider.run_turn(external_thread_id, prompt, run_config):
            output_limit_reached = False
            with self.database.transaction() as db:
                current = db.get(AgentRunRecord, run_id)
                if current is None or current.status == "cancelled":
                    return
                session = db.get(SessionRecord, current.session_id)
                thread = db.get(AgentThreadRecord, current.thread_id)
                assert session is not None and thread is not None
                if event.kind == "started":
                    current.status = "streaming"
                    current.external_turn_id = event.turn_id
                    session.agent_status = "busy"
                    created_message = AgentMessageRecord(
                        run_id=current.id,
                        role="assistant",
                        message_type="answer",
                        sequence=1,
                        status="streaming",
                    )
                    db.add(created_message)
                    db.flush()
                    emit_ui_event(db, "agent.streaming", current.id, run_payload(current))
                elif event.kind == "delta":
                    delta_message = db.scalar(
                        select(AgentMessageRecord).where(AgentMessageRecord.run_id == current.id)
                    )
                    assert delta_message is not None
                    remaining = MAX_AGENT_OUTPUT_CHARACTERS - len(delta_message.text)
                    applied_delta = event.text[: max(0, remaining)]
                    delta_message.text += applied_delta
                    delta_payload = message_payload(delta_message)
                    # A delta event must contain only the newly appended text.
                    # Persisting the full accumulated answer on every chunk makes
                    # ui_events grow quadratically for long streaming responses.
                    delta_payload["text"] = applied_delta
                    emit_ui_event(db, "agent.delta", current.id, delta_payload)
                    if len(event.text) > remaining:
                        current.status = "failed"
                        current.completed_at = utc_now()
                        current.error_type = "output_limit"
                        current.error_message = "Agent output exceeded the safety limit."
                        delta_message.status = "failed"
                        session.agent_status = "error"
                        emit_ui_event(db, "agent.failed", current.id, run_payload(current))
                        output_limit_reached = True
                elif event.kind == "completed":
                    if persist_thread_after_first_turn:
                        thread.external_thread_id = external_thread_id
                        emit_ui_event(
                            db,
                            "agent.thread",
                            thread.id,
                            {
                                "id": thread.id,
                                "external_thread_id": external_thread_id,
                                "status": "ready",
                            },
                        )
                    current.status = "completed"
                    current.completed_at = utc_now()
                    current.usage_metadata = event.metadata
                    thread.status = "ready"
                    thread.last_turn_at = current.completed_at
                    if current.context_end:
                        thread.last_completed_boundary = current.context_end
                    session.agent_status = "ready"
                    completed_message = db.scalar(
                        select(AgentMessageRecord).where(AgentMessageRecord.run_id == current.id)
                    )
                    if completed_message is not None:
                        completed_message.status = "completed"
                    emit_ui_event(db, "agent.completed", current.id, run_payload(current))
                    log_event(
                        "agent.completed",
                        session_id=current.session_id,
                        run_id=current.id,
                        state="completed",
                    )
                elif event.kind in {"failed", "interrupted"}:
                    current.status = "failed" if event.kind == "failed" else "interrupted"
                    current.completed_at = utc_now()
                    current.error_type = event.error_type or event.kind
                    current.error_message = event.error_message
                    session.agent_status = "error"
                    failed_message = db.scalar(
                        select(AgentMessageRecord).where(AgentMessageRecord.run_id == current.id)
                    )
                    if failed_message is not None:
                        failed_message.status = current.status
                    emit_ui_event(db, "agent.failed", current.id, run_payload(current))
                    log_event(
                        "agent.failed",
                        session_id=current.session_id,
                        run_id=current.id,
                        state=current.status,
                        error_type=current.error_type,
                    )
            if output_limit_reached:
                with contextlib.suppress(Exception):
                    await provider.cancel_turn(external_thread_id, event.turn_id or "")
                return

    def _fail_run(self, run_id: str, error: Exception) -> None:
        with self.database.transaction() as db:
            run = db.get(AgentRunRecord, run_id)
            if run is None or run.status in {"completed", "cancelled", "failed"}:
                return
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error_type = (
                "total_timeout"
                if isinstance(error, AgentTotalTimeoutError)
                else type(error).__name__
            )
            run.error_message = str(error)[:20_000]
            session = db.get(SessionRecord, run.session_id)
            if session is not None:
                session.agent_status = "unavailable"
            message = db.scalar(
                select(AgentMessageRecord).where(AgentMessageRecord.run_id == run.id)
            )
            if message is not None:
                message.status = "failed"
            emit_ui_event(db, "agent.failed", run.id, run_payload(run))
            log_event(
                "agent.failed",
                session_id=run.session_id,
                run_id=run.id,
                state="failed",
                error_type=run.error_type,
            )
