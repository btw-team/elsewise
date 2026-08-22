import asyncio
import contextlib
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import and_, func, or_, select

from elsewise import __version__
from elsewise.agents.app_server import CodexAppServerProvider
from elsewise.agents.claude_cli import ClaudeCodeProvider
from elsewise.agents.interface import AgentProvider
from elsewise.agents.queue import AgentQueueManager, message_payload, run_payload
from elsewise.api.cursors import (
    agent_cursor,
    parse_agent_cursor,
    parse_utterance_cursor,
    utterance_cursor,
)
from elsewise.api.schemas import (
    ActionPresetCreate,
    ActionPresetUpdate,
    AgentActionCreate,
    ButtonCreate,
    ButtonUpdate,
    GlobalSettingsUpdate,
    PairingTokenUpdate,
    SessionCreate,
    SessionUpdate,
)
from elsewise.api.security import safe_http_request, safe_ui_websocket
from elsewise.api.serialization import (
    segment_payload,
    source_payload,
    ui_event_payload,
    utterance_payload,
)
from elsewise.exports import ExportService
from elsewise.observability import RuntimeDiagnostics
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    AgentMessageRecord,
    AgentRunRecord,
    AgentThreadRecord,
    ButtonDefinitionRecord,
    CaptionEventCounterRecord,
    CaptureSourceRecord,
    MaintenanceStateRecord,
    RecordingSegmentRecord,
    SessionRecord,
    UiEventRecord,
    UtteranceRecord,
)
from elsewise.services.action_presets import ActionPresetService
from elsewise.services.buttons import ButtonService, button_payload
from elsewise.services.errors import ServiceError
from elsewise.services.runtime_status import RuntimeStatusService
from elsewise.services.sessions import SessionService, prepare_agent_cwd, session_payload
from elsewise.services.speaker_identity import classify_speaker, own_speaker_names
from elsewise.settings.config import DEFAULT_INITIAL_PROMPTS, SettingsStore
from elsewise.settings.languages import SUPPORTED_LANGUAGE_SET
from elsewise.settings.limits import STOP_FINALIZE_GRACE_SECONDS, UI_SEND_TIMEOUT_SECONDS
from elsewise.settings.pairing import PairingManager

router = APIRouter(prefix="/api")


def database_from_request(request: Request) -> Database:
    return cast(Database, request.app.state.database)


DatabaseDependency = Annotated[Database, Depends(database_from_request)]


def _require_local_origin(request: Request) -> None:
    if not safe_http_request(request):
        raise HTTPException(status_code=403, detail="invalid_origin")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "data_directory": str(request.app.state.paths.data),
    }


@router.get("/runtime/status")
async def runtime_status(request: Request) -> dict[str, Any]:
    service = cast(RuntimeStatusService, request.app.state.runtime_status)
    return await service.snapshot()


@router.get("/extension/pairing")
def pairing_metadata(request: Request) -> dict[str, Any]:
    _require_local_origin(request)
    pairing: PairingManager = request.app.state.pairing
    metadata = pairing.metadata()
    return {
        "token": pairing.token(),
        "masked_token": metadata.masked_token,
        "created_at": metadata.created_at,
        "generation": metadata.generation,
    }


@router.put("/extension/pairing")
def update_pairing(body: PairingTokenUpdate, request: Request) -> dict[str, Any]:
    _require_local_origin(request)
    pairing: PairingManager = request.app.state.pairing
    metadata = pairing.save(body.token)
    return {
        "token": pairing.token(),
        "masked_token": metadata.masked_token,
        "created_at": metadata.created_at,
        "generation": metadata.generation,
    }


@router.post("/extension/pairing/regenerate")
def regenerate_pairing(request: Request) -> dict[str, Any]:
    _require_local_origin(request)
    pairing: PairingManager = request.app.state.pairing
    token = pairing.regenerate()
    metadata = pairing.metadata()
    return {
        "token": token,
        "masked_token": metadata.masked_token,
        "created_at": metadata.created_at,
        "generation": metadata.generation,
    }


async def _validate_agent_selection(
    request: Request,
    provider_id: str,
    model: str | None,
    reasoning_effort: str | None,
) -> None:
    manager: AgentQueueManager = request.app.state.agent_queue
    if provider_id not in manager.providers.ids:
        raise HTTPException(status_code=422, detail="invalid_agent_provider")
    if model is None:
        if reasoning_effort is not None:
            raise HTTPException(status_code=422, detail="agent_reasoning_requires_model")
        return
    health = await manager.health(provider_id)
    if health.status != "ready":
        return
    models = await manager.models(provider_id)
    selected = next((item for item in models if item.id == model), None)
    if selected is None:
        raise HTTPException(status_code=422, detail="invalid_agent_model")
    if reasoning_effort is not None and reasoning_effort not in selected.reasoning_efforts:
        raise HTTPException(status_code=422, detail="invalid_agent_reasoning_effort")


@router.post("/sessions", status_code=201)
async def create_session(
    body: SessionCreate, request: Request, database: DatabaseDependency
) -> dict[str, Any]:
    values = body.model_dump()
    provided_fields = body.model_fields_set
    create_agent_cwd = values.pop("create_agent_cwd")
    store = cast(SettingsStore, request.app.state.settings)
    configured = store.load()
    if values["language"] is None:
        values["language"] = configured.default_meeting_language
    if values["agent_provider"] is None:
        values["agent_provider"] = configured.default_agent_provider
    if values["agent_provider"] not in {"codex", "claude"}:
        raise HTTPException(status_code=422, detail="invalid_agent_provider")
    use_global_agent_defaults = values["agent_provider"] == configured.default_agent_provider
    if "agent_model" not in provided_fields:
        values["agent_model"] = (
            configured.default_agent_model if use_global_agent_defaults else None
        )
    if "agent_reasoning_effort" not in provided_fields:
        values["agent_reasoning_effort"] = (
            configured.default_agent_reasoning_effort if use_global_agent_defaults else None
        )
    await _validate_agent_selection(
        request,
        values["agent_provider"],
        values["agent_model"],
        values["agent_reasoning_effort"],
    )
    if values["initial_prompt"] is None:
        language_key = values["language"]
        values["initial_prompt"] = configured.initial_prompts.get(
            language_key,
            configured.initial_prompts.get(language_key.split("-")[0], ""),
        )
    if not values["initial_prompt"].strip():
        raise HTTPException(status_code=422, detail="invalid_initial_prompt")
    if values["allow_workspace_write"] is None:
        values["allow_workspace_write"] = configured.default_allow_workspace_write
    if values["allow_network"] is None:
        values["allow_network"] = configured.default_allow_network
    values["requested_agent_cwd"] = prepare_agent_cwd(
        values["requested_agent_cwd"], create_missing=create_agent_cwd
    )
    record = SessionService(database).create(**values)
    return session_payload(record)


@router.get("/sessions")
def list_sessions(database: DatabaseDependency) -> list[dict[str, Any]]:
    return [session_payload(record) for record in SessionService(database).list_all()]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, database: DatabaseDependency) -> dict[str, Any]:
    return session_payload(SessionService(database).get(session_id))


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str, body: SessionUpdate, request: Request, database: DatabaseDependency
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    create_agent_cwd = bool(values.pop("create_agent_cwd", False))
    nullable_keys = {
        "requested_agent_cwd",
        "action_preset_id",
        "agent_model",
        "agent_reasoning_effort",
    }
    changes = {
        key: value for key, value in values.items() if value is not None or key in nullable_keys
    }
    if "agent_provider" in changes and changes["agent_provider"] not in {"codex", "claude"}:
        raise HTTPException(status_code=422, detail="invalid_agent_provider")
    if "agent_provider" in changes:
        if "agent_model" not in body.model_fields_set:
            changes["agent_model"] = None
        if "agent_reasoning_effort" not in body.model_fields_set:
            changes["agent_reasoning_effort"] = None
    if "initial_prompt" in changes and not changes["initial_prompt"].strip():
        raise HTTPException(status_code=422, detail="invalid_initial_prompt")
    service = SessionService(database)
    current = service.get(session_id)
    if {"agent_provider", "agent_model", "agent_reasoning_effort"}.intersection(changes):
        await _validate_agent_selection(
            request,
            str(changes.get("agent_provider", current.agent_provider)),
            changes.get("agent_model", current.agent_model),
            changes.get("agent_reasoning_effort", current.agent_reasoning_effort),
        )
    record = service.update(session_id, changes, create_agent_cwd=create_agent_cwd)
    if "requested_agent_cwd" in changes:
        manager: AgentQueueManager = request.app.state.agent_queue
        manager.refresh_session_cwd(session_id)
        record = SessionService(database).get(session_id)
    return session_payload(record)


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    store: SettingsStore = request.app.state.settings
    settings = store.load().model_dump()
    settings["recovery"] = (
        {
            "file_name": store.recovery_notice.file_name,
            "source": store.recovery_notice.source,
        }
        if store.recovery_notice
        else None
    )
    return settings


@router.patch("/settings")
async def update_settings(body: GlobalSettingsUpdate, request: Request) -> dict[str, Any]:
    store: SettingsStore = request.app.state.settings
    current = store.load()
    changes = body.model_dump(exclude_none=True)
    for key in ("default_agent_model", "default_agent_reasoning_effort"):
        if key in body.model_fields_set:
            changes[key] = getattr(body, key)
    if changes.get("default_agent_provider") not in {None, "codex", "claude"}:
        raise HTTPException(status_code=422, detail="invalid_agent_provider")
    if "default_agent_provider" in changes:
        if "default_agent_model" not in body.model_fields_set:
            changes["default_agent_model"] = None
        if "default_agent_reasoning_effort" not in body.model_fields_set:
            changes["default_agent_reasoning_effort"] = None
    if {
        "default_agent_provider",
        "default_agent_model",
        "default_agent_reasoning_effort",
    }.intersection(changes):
        await _validate_agent_selection(
            request,
            str(changes.get("default_agent_provider", current.default_agent_provider)),
            changes.get("default_agent_model", current.default_agent_model),
            changes.get(
                "default_agent_reasoning_effort",
                current.default_agent_reasoning_effort,
            ),
        )
    prompts = changes.get("initial_prompts")
    if prompts is not None:
        merged = dict(current.initial_prompts)
        for language, prompt in prompts.items():
            if language not in SUPPORTED_LANGUAGE_SET or not prompt.strip() or len(prompt) > 20_000:
                raise HTTPException(status_code=422, detail="invalid_initial_prompt")
            merged[language] = prompt
        changes["initial_prompts"] = merged
        changes["initial_prompt_version"] = current.initial_prompt_version + 1
    executable_changes = {
        key: str(changes[key])
        for key in ("codex_executable", "claude_executable")
        if key in changes and changes[key] != getattr(current, key)
    }
    manager: AgentQueueManager = request.app.state.agent_queue
    replaced: list[tuple[str, AgentProvider]] = []
    try:
        for setting_key, executable in executable_changes.items():
            provider_id = "codex" if setting_key == "codex_executable" else "claude"
            replacement: AgentProvider = (
                CodexAppServerProvider(executable)
                if provider_id == "codex"
                else ClaudeCodeProvider(executable)
            )
            previous = await manager.replace_provider(provider_id, replacement)
            replaced.append((provider_id, previous))
        updated = store.update(changes).model_dump()
        updated["recovery"] = (
            {
                "file_name": store.recovery_notice.file_name,
                "source": store.recovery_notice.source,
            }
            if store.recovery_notice
            else None
        )
        return updated
    except Exception:
        for provider_id, previous in reversed(replaced):
            with contextlib.suppress(Exception):
                await manager.replace_provider(provider_id, previous)
        raise


@router.post("/settings/initial-prompts/reset")
def reset_initial_prompts(request: Request) -> dict[str, Any]:
    store: SettingsStore = request.app.state.settings
    current = store.load()
    updated = store.update(
        {
            "initial_prompts": dict(DEFAULT_INITIAL_PROMPTS),
            "initial_prompt_version": current.initial_prompt_version + 1,
        }
    ).model_dump()
    updated["recovery"] = (
        {
            "file_name": store.recovery_notice.file_name,
            "source": store.recovery_notice.source,
        }
        if store.recovery_notice
        else None
    )
    return updated


@router.get("/buttons")
def list_buttons(database: DatabaseDependency) -> list[dict[str, Any]]:
    return [button_payload(record) for record in ButtonService(database).list_all()]


@router.post("/buttons", status_code=201)
def create_button(body: ButtonCreate, database: DatabaseDependency) -> dict[str, Any]:
    return button_payload(ButtonService(database).create(body.model_dump()))


@router.patch("/buttons/{button_id}")
def update_button(
    button_id: str, body: ButtonUpdate, database: DatabaseDependency
) -> dict[str, Any]:
    return button_payload(
        ButtonService(database).update(button_id, body.model_dump(exclude_none=True))
    )


@router.delete("/buttons/{button_id}", status_code=204)
def delete_button(button_id: str, database: DatabaseDependency) -> Response:
    ButtonService(database).delete(button_id)
    return Response(status_code=204)


@router.get("/action-presets")
def list_action_presets(database: DatabaseDependency) -> list[dict[str, Any]]:
    return ActionPresetService(database).list_all()


@router.post("/action-presets", status_code=201)
def create_action_preset(body: ActionPresetCreate, database: DatabaseDependency) -> dict[str, Any]:
    return ActionPresetService(database).create(body.name, body.button_ids)


@router.patch("/action-presets/{preset_id}")
def update_action_preset(
    preset_id: str, body: ActionPresetUpdate, database: DatabaseDependency
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    return ActionPresetService(database).update(
        preset_id,
        name=values.get("name"),
        button_ids=values.get("button_ids"),
    )


@router.delete("/action-presets/{preset_id}", status_code=204)
def delete_action_preset(preset_id: str, database: DatabaseDependency) -> Response:
    ActionPresetService(database).delete(preset_id)
    return Response(status_code=204)


@router.post("/sessions/{session_id}/start")
def start_session(
    session_id: str, request: Request, database: DatabaseDependency
) -> dict[str, Any]:
    manager: AgentQueueManager = request.app.state.agent_queue
    if manager.draining:
        raise HTTPException(status_code=409, detail="agent_queue_draining")
    SessionService(database).start(session_id)
    # Enqueue is durable and fast; the background worker owns all agent I/O.
    manager.ensure_initial_run(session_id)
    return session_payload(SessionService(database).get(session_id))


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    session_id: str, request: Request, database: DatabaseDependency
) -> dict[str, Any]:
    record = SessionService(database).stop(session_id)

    async def cleanup() -> None:
        await asyncio.sleep(STOP_FINALIZE_GRACE_SECONDS)
        SessionService(database).cleanup_partial_utterances(session_id)

    task = asyncio.create_task(cleanup(), name=f"finalize-session-{session_id}")
    cleanup_tasks: set[asyncio.Task[None]] = request.app.state.session_cleanup_tasks
    cleanup_tasks.add(task)
    task.add_done_callback(cleanup_tasks.discard)
    return session_payload(record)


@router.get("/agent/providers")
async def agent_providers(request: Request) -> dict[str, Any]:
    manager: AgentQueueManager = request.app.state.agent_queue
    health_by_provider = await manager.health_all(refresh=True)
    models_by_provider = await manager.models_all()
    return {
        "providers": [
            {
                "id": provider_id,
                "name": "Claude Code" if provider_id == "claude" else "Codex",
                "status": health.status,
                "version": health.version,
                "authenticated": health.authenticated,
                "message": health.message,
                "models": [
                    {
                        "id": model.id,
                        "name": model.name,
                        "description": model.description,
                        "reasoning_efforts": list(model.reasoning_efforts),
                        "default_reasoning_effort": model.default_reasoning_effort,
                    }
                    for model in models_by_provider.get(provider_id, ())
                ],
            }
            for provider_id, health in health_by_provider.items()
        ]
    }


@router.get("/diagnostics")
async def safe_diagnostics(request: Request, database: DatabaseDependency) -> dict[str, Any]:
    manager: AgentQueueManager = request.app.state.agent_queue
    agent_health = await manager.health_all()
    with database.transaction() as db:
        session_states: dict[str, int] = {
            state: count
            for state, count in db.execute(
                select(SessionRecord.recording_status, func.count(SessionRecord.id)).group_by(
                    SessionRecord.recording_status
                )
            ).tuples()
        }
        source_platforms: dict[str, int] = {
            platform: count
            for platform, count in db.execute(
                select(
                    CaptureSourceRecord.platform, func.count(CaptureSourceRecord.source_id)
                ).group_by(CaptureSourceRecord.platform)
            ).tuples()
        }
        run_states: dict[str, int] = {
            status: count
            for status, count in db.execute(
                select(AgentRunRecord.status, func.count(AgentRunRecord.id)).group_by(
                    AgentRunRecord.status
                )
            ).tuples()
        }
        event_count = db.scalar(select(func.count(UiEventRecord.id))) or 0
        caption_event_counters = [
            {
                "event_type": record.event_type,
                "result": record.processing_result,
                "reason_code": record.reason_code,
                "protocol_version": record.protocol_version,
                "count": record.count,
            }
            for record in db.scalars(
                select(CaptionEventCounterRecord).order_by(
                    CaptionEventCounterRecord.event_type,
                    CaptionEventCounterRecord.processing_result,
                    CaptionEventCounterRecord.reason_code,
                )
            )
        ]
    return {
        "daemon": "ok",
        "version": __version__,
        "agents": {
            provider_id: {
                "status": health.status,
                "version": health.version,
                "authenticated": health.authenticated,
            }
            for provider_id, health in agent_health.items()
        },
        "sessions": session_states,
        "sources": source_platforms,
        "agent_runs": run_states,
        "ui_event_count": event_count,
        "caption_event_counters": caption_event_counters,
        "runtime": cast(RuntimeDiagnostics, request.app.state.diagnostics).snapshot(),
    }


@router.get("/sessions/{session_id}/agent-runs")
def list_agent_runs(
    session_id: str, request: Request, database: DatabaseDependency
) -> list[dict[str, Any]]:
    SessionService(database).get(session_id)
    manager: AgentQueueManager = request.app.state.agent_queue
    return [run_payload(run) for run in manager.list_runs(session_id)]


@router.post("/sessions/{session_id}/agent-runs", status_code=201)
def create_agent_run(
    session_id: str,
    body: AgentActionCreate,
    request: Request,
    database: DatabaseDependency,
) -> dict[str, Any]:
    _ = database
    manager: AgentQueueManager = request.app.state.agent_queue
    if body.prompt is not None:
        return run_payload(manager.enqueue_prompt(session_id, body.prompt))
    assert body.button_id is not None
    return run_payload(manager.enqueue_action(session_id, body.button_id))


@router.post("/agent-runs/{run_id}/cancel")
async def cancel_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    manager: AgentQueueManager = request.app.state.agent_queue
    return run_payload(await manager.cancel(run_id))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    request: Request,
    database: DatabaseDependency,
    confirm: str = Query(min_length=1),
) -> Response:
    if confirm != session_id:
        raise HTTPException(status_code=400, detail="confirmation_mismatch")
    record = SessionService(database).get(session_id)
    if record.recording_status == "running":
        raise HTTPException(status_code=409, detail="session_running")
    ExportService(database, request.app.state.paths.exports).cleanup(session_id)
    SessionService(database).delete(session_id)
    return Response(status_code=204)


@router.post("/sessions/{session_id}/export")
def export_session(
    session_id: str, request: Request, database: DatabaseDependency
) -> dict[str, str]:
    result = ExportService(database, request.app.state.paths.exports).export(session_id)
    return {
        "directory": str(result.directory),
        "captions_path": str(result.captions_path),
        "agent_path": str(result.agent_path),
    }


@router.get("/sessions/{session_id}/utterances")
def list_utterances(
    session_id: str,
    request: Request,
    database: DatabaseDependency,
    limit: int = Query(default=500, ge=1, le=1000),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    SessionService(database).get(session_id)
    boundary = parse_utterance_cursor(cursor)
    with database.transaction() as db:
        statement = select(UtteranceRecord).where(UtteranceRecord.session_id == session_id)
        if boundary is not None:
            before_at, before_seq, before_id = boundary
            statement = statement.where(
                or_(
                    UtteranceRecord.first_observed_at < before_at,
                    and_(
                        UtteranceRecord.first_observed_at == before_at,
                        or_(
                            UtteranceRecord.first_client_seq < before_seq,
                            and_(
                                UtteranceRecord.first_client_seq == before_seq,
                                UtteranceRecord.id < before_id,
                            ),
                        ),
                    ),
                )
            )
        records = list(
            db.scalars(
                statement.order_by(
                    UtteranceRecord.first_observed_at.desc(),
                    UtteranceRecord.first_client_seq.desc(),
                    UtteranceRecord.id.desc(),
                ).limit(limit + 1)
            )
        )
        has_more = len(records) > limit
        records = records[:limit]
        source_ids = {record.source_id for record in records}
        sources = list(
            db.scalars(
                select(CaptureSourceRecord).where(CaptureSourceRecord.source_id.in_(source_ids))
            )
        )
    records.reverse()
    source_platforms = {source.source_id: source.platform for source in sources}
    configured_names = own_speaker_names(cast(SettingsStore, request.app.state.settings).load())
    items = [
        utterance_payload(
            record,
            speaker_role=classify_speaker(
                record.speaker,
                source_platforms.get(record.source_id),
                configured_names,
            ),
        )
        for record in records
    ]
    next_cursor = (
        utterance_cursor(
            records[0].first_observed_at,
            records[0].first_client_seq,
            records[0].id,
        )
        if records and has_more
        else None
    )
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


@router.get("/sessions/{session_id}/agent-history")
def agent_history(
    session_id: str,
    database: DatabaseDependency,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    SessionService(database).get(session_id)
    boundary = parse_agent_cursor(cursor)
    with database.transaction() as db:
        statement = select(AgentRunRecord).where(AgentRunRecord.session_id == session_id)
        if boundary is not None:
            before_sequence, before_id = boundary
            statement = statement.where(
                or_(
                    AgentRunRecord.queue_sequence < before_sequence,
                    and_(
                        AgentRunRecord.queue_sequence == before_sequence,
                        AgentRunRecord.id < before_id,
                    ),
                )
            )
        runs = list(
            db.scalars(
                statement.order_by(
                    AgentRunRecord.queue_sequence.desc(), AgentRunRecord.id.desc()
                ).limit(limit + 1)
            )
        )
        has_more = len(runs) > limit
        runs = runs[:limit]
        run_ids = [run.id for run in runs]
        messages = (
            list(
                db.scalars(
                    select(AgentMessageRecord)
                    .where(AgentMessageRecord.run_id.in_(run_ids))
                    .order_by(AgentMessageRecord.created_at, AgentMessageRecord.sequence)
                )
            )
            if run_ids
            else []
        )
    runs.reverse()
    next_cursor = agent_cursor(runs[0].queue_sequence, runs[0].id) if runs and has_more else None
    return {
        "runs": [run_payload(run) for run in runs],
        "messages": [message_payload(message) for message in messages],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.get("/sessions/{session_id}/segments")
def list_segments(session_id: str, database: DatabaseDependency) -> list[dict[str, Any]]:
    SessionService(database).get(session_id)
    with database.transaction() as db:
        records = list(
            db.scalars(
                select(RecordingSegmentRecord)
                .where(RecordingSegmentRecord.session_id == session_id)
                .order_by(RecordingSegmentRecord.sequence)
            )
        )
    return [segment_payload(record) for record in records]


@router.get("/sessions/{session_id}/detail")
def session_detail(
    session_id: str, request: Request, database: DatabaseDependency
) -> dict[str, Any]:
    session = SessionService(database).get(session_id)
    with database.transaction() as db:
        segments = list(
            db.scalars(
                select(RecordingSegmentRecord)
                .where(RecordingSegmentRecord.session_id == session_id)
                .order_by(RecordingSegmentRecord.sequence)
            )
        )
        thread = db.scalar(
            select(AgentThreadRecord).where(AgentThreadRecord.session_id == session_id)
        )
        state = db.get(MaintenanceStateRecord, 1)
        pruned_through = state.ui_events_pruned_through if state else 0
        last_event_id = max(db.scalar(select(func.max(UiEventRecord.id))) or 0, pruned_through)

    utterance_page = list_utterances(session_id, request, database, limit=500, cursor=None)
    history_page = agent_history(session_id, database, limit=50, cursor=None)
    return {
        "session": session_payload(session),
        "segments": [segment_payload(record) for record in segments],
        "agent_thread": (
            {
                "id": thread.id,
                "session_id": thread.session_id,
                "provider": thread.provider,
                "external_thread_id": thread.external_thread_id,
                "status": thread.status,
                "created_at": thread.created_at.isoformat(),
                "resumed_at": thread.resumed_at.isoformat() if thread.resumed_at else None,
                "last_turn_at": thread.last_turn_at.isoformat() if thread.last_turn_at else None,
            }
            if thread
            else None
        ),
        "utterances": utterance_page,
        "agent_history": history_page,
        "last_event_id": last_event_id,
        "pruned_through": pruned_through,
    }


@router.get("/snapshot")
def snapshot(request: Request, database: DatabaseDependency) -> dict[str, Any]:
    with database.transaction() as db:
        sessions = list(db.scalars(select(SessionRecord).order_by(SessionRecord.created_at.desc())))
        sources = list(
            db.scalars(
                select(CaptureSourceRecord)
                .where(
                    or_(
                        CaptureSourceRecord.connected.is_(True),
                        CaptureSourceRecord.enabled.is_(True),
                    )
                )
                .order_by(CaptureSourceRecord.updated_at.desc())
            )
        )
        buttons = list(
            db.scalars(select(ButtonDefinitionRecord).order_by(ButtonDefinitionRecord.created_at))
        )
        state = db.get(MaintenanceStateRecord, 1)
        pruned_through = state.ui_events_pruned_through if state else 0
        last_event_id = max(db.scalar(select(func.max(UiEventRecord.id))) or 0, pruned_through)
    return {
        "sessions": [session_payload(record) for record in sessions],
        "sources": [source_payload(record) for record in sources],
        "buttons": [button_payload(record) for record in buttons],
        "action_presets": ActionPresetService(database).list_all(),
        "last_event_id": last_event_id,
        "pruned_through": pruned_through,
    }


@router.get("/ui-events")
def replay_ui_events(
    database: DatabaseDependency,
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict[str, Any]:
    with database.transaction() as db:
        state = db.get(MaintenanceStateRecord, 1)
        pruned_through = state.ui_events_pruned_through if state else 0
        maximum = max(db.scalar(select(func.max(UiEventRecord.id))) or 0, pruned_through)
        if since < pruned_through or since > maximum:
            raise ServiceError(
                "ui_event_cursor_pruned",
                "The UI event cursor is no longer available; reload the snapshot.",
                status_code=409,
            )
        events = list(
            db.scalars(
                select(UiEventRecord)
                .where(UiEventRecord.id > since)
                .order_by(UiEventRecord.id)
                .limit(limit + 1)
            )
        )
    return {
        "events": [ui_event_payload(event) for event in events[:limit]],
        "has_more": len(events) > limit,
        "pruned_through": pruned_through,
        "last_event_id": maximum,
    }


async def ui_websocket(websocket: WebSocket) -> None:
    if not safe_ui_websocket(websocket):
        await websocket.close(code=1008, reason="invalid_origin")
        return
    await websocket.accept()
    diagnostics = cast(RuntimeDiagnostics, websocket.app.state.diagnostics)
    diagnostics.connected("ui")
    database: Database = websocket.app.state.database
    disconnect_task = asyncio.create_task(
        _wait_for_websocket_disconnect(websocket), name="elsewise-ui-disconnect"
    )
    try:
        raw_since = websocket.query_params.get("since", "0")
        try:
            since = int(raw_since)
        except ValueError:
            since = -1
        with database.transaction() as db:
            state = db.get(MaintenanceStateRecord, 1)
            pruned_through = state.ui_events_pruned_through if state else 0
            maximum = max(db.scalar(select(func.max(UiEventRecord.id))) or 0, pruned_through)
            invalid = since < pruned_through or since > maximum
            if invalid:
                events: list[UiEventRecord] = []
            else:
                events = list(
                    db.scalars(
                        select(UiEventRecord)
                        .where(UiEventRecord.id > since)
                        .order_by(UiEventRecord.id)
                        .limit(500)
                    )
                )
        if invalid:
            await asyncio.wait_for(
                websocket.send_json(
                    {
                        "type": "ui.event",
                        "protocol_version": 1,
                        "event_id": maximum,
                        "event_type": "resync_required",
                        "aggregate_id": None,
                        "created_at": "1970-01-01T00:00:00.000Z",
                        "payload": {},
                    }
                ),
                timeout=UI_SEND_TIMEOUT_SECONDS,
            )
            cursor = maximum
        else:
            for event in events:
                await asyncio.wait_for(
                    websocket.send_json(ui_event_payload(event)),
                    timeout=UI_SEND_TIMEOUT_SECONDS,
                )
            cursor = events[-1].id if events else since
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(disconnect_task), timeout=0.25)
                return
            except TimeoutError:
                pass
            with database.transaction() as db:
                new_events = list(
                    db.scalars(
                        select(UiEventRecord)
                        .where(UiEventRecord.id > cursor)
                        .order_by(UiEventRecord.id)
                        .limit(500)
                    )
                )
            for event in new_events:
                await asyncio.wait_for(
                    websocket.send_json(ui_event_payload(event)),
                    timeout=UI_SEND_TIMEOUT_SECONDS,
                )
                cursor = event.id
    except (WebSocketDisconnect, TimeoutError):
        return
    finally:
        disconnect_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await disconnect_task
        diagnostics.disconnected("ui")


async def _wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
