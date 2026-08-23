import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from elsewise.agents.fake import FakeAgentProvider
from elsewise.agents.registry import AgentProviderRegistry
from elsewise.main import create_app
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    AgentMessageRecord,
    AgentRunRecord,
    AgentThreadRecord,
    ButtonDefinitionRecord,
    CaptionEventCounterRecord,
    CaptionEventDiagnosticRecord,
    CaptionEventTombstoneRecord,
    RecordingSegmentRecord,
    UiEventRecord,
    UtteranceRecord,
)
from elsewise.protocol.models import SourceStatus, UtteranceFinalize, UtteranceUpsert
from elsewise.services.action_presets import MAX_ACTION_PRESETS, ActionPresetService
from elsewise.services.builtin_actions import BUILTIN_ACTIONS, BUILTIN_PRESETS
from elsewise.services.buttons import MAX_ACTIONS, ButtonService
from elsewise.services.capture import CaptureService
from elsewise.services.errors import ServiceError
from elsewise.services.sessions import SessionService, recover_after_restart
from elsewise.settings.config import DEFAULT_INITIAL_PROMPTS
from elsewise.settings.languages import SUPPORTED_LANGUAGES
from elsewise.settings.paths import AppPaths
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, inspect, select

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_action_and_preset_limits_are_enforced_by_services(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "action-limits.sqlite3")
    database.migrate()
    buttons = ButtonService(database)
    presets = ActionPresetService(database)

    for index in range(MAX_ACTION_PRESETS - len(BUILTIN_PRESETS)):
        presets.create(f"Preset {index}", [])
    with pytest.raises(ServiceError, match="No more than 24") as preset_limit:
        presets.create("One too many", [])
    assert preset_limit.value.code == "preset_limit_reached"

    with database.transaction() as db:
        for index in range(MAX_ACTIONS - len(BUILTIN_ACTIONS)):
            db.add(
                ButtonDefinitionRecord(
                    key=f"limit_{index}",
                    label=f"Limit {index}",
                    prompt_template="Prompt",
                    context_strategy="all",
                    context_value=1,
                    hard_character_cap=1_000,
                )
            )
    with pytest.raises(ServiceError, match="No more than 288") as action_limit:
        buttons.create(
            {
                "label": "One too many",
                "prompt_template": "Prompt",
                "context_strategy": "all",
                "context_value": 1,
                "hard_character_cap": 1_000,
            }
        )
    assert action_limit.value.code == "action_limit_reached"
    database.dispose()


def make_database(path: Path) -> Database:
    database = Database.from_path(path)
    database.create_schema()
    return database


def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        data=tmp_path,
        config=tmp_path / "config",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        database=tmp_path / "database.sqlite3",
        exports=tmp_path / "exports",
        diagnostics=tmp_path / "diagnostics",
        agent_empty_cwd=tmp_path / "runtime" / "agent-empty-cwd",
    )


def source_status(*, captions_status: str = "on_empty") -> SourceStatus:
    return SourceStatus.model_validate(
        {
            "type": "source.status",
            "protocol_version": 1,
            "event_id": str(uuid4()),
            "source_id": "meet-document",
            "client_seq": 1,
            "platform": "google_meet",
            "enabled": True,
            "captions_status": captions_status,
            "speaker_detection": "available",
            "meeting_key": "safe-meeting-key",
            "observed_at": NOW.isoformat(),
        }
    )


def caption(
    message_type: str,
    *,
    sequence: int,
    revision: int,
    text: str,
    event_id: str | None = None,
) -> UtteranceUpsert | UtteranceFinalize:
    model = UtteranceUpsert if message_type == "utterance.upsert" else UtteranceFinalize
    return model.model_validate(
        {
            "type": message_type,
            "protocol_version": 1,
            "event_id": event_id or str(uuid4()),
            "source_id": "meet-document",
            "client_seq": sequence,
            "platform": "google_meet",
            "meeting_key": "safe-meeting-key",
            "utterance_id": "caption-1",
            "revision": revision,
            "speaker": "Иван",
            "text": text,
            "observed_at": NOW.isoformat(),
        }
    )


@pytest.mark.integration
def test_database_startup_migration_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "startup-migration.sqlite3"
    database = Database.from_path(database_path)
    database.migrate()
    database.migrate()

    with database.engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
    assert revision == "0001_initial"
    assert "sessions" in inspect(database.engine).get_table_names()
    database.dispose()


@pytest.mark.integration
def test_caption_commit_revision_finalize_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "capture.sqlite3"
    database = make_database(path)
    sessions = SessionService(database)
    capture_service = CaptureService(database)
    session = sessions.create(title="Planning")
    assert capture_service.update_source(source_status(), installation_id=str(uuid4())) == "applied"
    sessions.start(session.id, now=NOW)

    first_id = str(uuid4())
    first = caption("utterance.upsert", sequence=2, revision=1, text="Нам", event_id=first_id)
    assert capture_service.process_caption(first) == "applied"
    assert capture_service.process_caption(first) == "duplicate"
    assert (
        capture_service.process_caption(
            caption("utterance.upsert", sequence=3, revision=1, text="Нам старое")
        )
        == "stale"
    )
    assert (
        capture_service.process_caption(
            caption("utterance.upsert", sequence=4, revision=2, text="Нам нужно")
        )
        == "applied"
    )
    assert (
        capture_service.process_caption(
            caption("utterance.finalize", sequence=5, revision=2, text="Нам нужно")
        )
        == "applied"
    )

    with database.transaction() as db:
        utterance = db.scalar(select(UtteranceRecord))
        assert utterance is not None
        assert (utterance.text, utterance.revision, utterance.final) == ("Нам нужно", 2, True)
        assert db.scalar(select(func.count(CaptionEventTombstoneRecord.event_id))) == 4
        diagnostics = list(db.scalars(select(CaptionEventDiagnosticRecord.processing_result)))
        assert diagnostics == ["stale"]
        counters: dict[str, int] = {}
        for record in db.scalars(select(CaptionEventCounterRecord)):
            counters[record.processing_result] = (
                counters.get(record.processing_result, 0) + record.count
            )
        assert counters == {"applied": 3, "stale": 1}
        assert db.scalar(select(func.count(UiEventRecord.id))) == 6
    database.dispose()

    reopened = make_database(path)
    assert SessionService(reopened).get(session.id).recording_status == "running"
    assert SessionService(reopened).utterances(session.id)[0].text == "Нам нужно"
    recover_after_restart(reopened)
    assert SessionService(reopened).get(session.id).recording_status == "stopped"
    assert SessionService(reopened).get(session.id).capture_status == "no_source"
    reopened.dispose()


@pytest.mark.integration
def test_one_running_session_and_restart_segments(tmp_path: Path) -> None:
    database = make_database(tmp_path / "sessions.sqlite3")
    service = SessionService(database)
    first = service.create(title="First")
    second = service.create(title="Second")

    def try_start(session_id: str) -> str:
        try:
            return service.start(session_id, now=NOW).id
        except ServiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(try_start, (first.id, second.id)))
    assert sum(result in (first.id, second.id) for result in results) == 1
    assert "another_session_running" in results

    running_id = next(result for result in results if result in (first.id, second.id))
    service.stop(running_id, now=NOW)
    service.start(running_id, now=NOW)
    with database.transaction() as db:
        segments = list(
            db.scalars(
                select(RecordingSegmentRecord)
                .where(RecordingSegmentRecord.session_id == running_id)
                .order_by(RecordingSegmentRecord.sequence)
            )
        )
        assert [segment.sequence for segment in segments] == [1, 2]
        assert segments[0].stopped_at is not None
    database.dispose()


def test_session_editability_follows_first_start_and_running_state(tmp_path: Path) -> None:
    database = make_database(tmp_path / "session-editability.sqlite3")
    service = SessionService(database)
    session = service.create(
        title="Before start",
        description="Initial description",
        language="en",
        initial_prompt="Initial prompt",
        agent_provider="codex",
        requested_agent_cwd=None,
        allow_workspace_write=False,
        allow_network=False,
    )

    before_start = service.update(
        session.id,
        {
            "language": "fr",
            "initial_prompt": "Prompt initial",
            "agent_provider": "claude",
        },
    )
    assert before_start.language == "fr"
    assert before_start.agent_provider == "claude"

    service.start(session.id, now=NOW)
    with pytest.raises(ServiceError) as running_edit:
        service.update(session.id, {"title": "While running"})
    assert running_edit.value.code == "session_running"

    service.stop(session.id, now=NOW + timedelta(minutes=1))
    after_stop = service.update(
        session.id,
        {
            "title": "After stop",
            "description": "Updated description",
            "agent_model": "new-model",
            "agent_reasoning_effort": "high",
            "allow_workspace_write": True,
            "allow_network": True,
        },
    )
    assert after_stop.title == "After stop"
    assert after_stop.description == "Updated description"
    assert after_stop.agent_model == "new-model"
    assert after_stop.agent_reasoning_effort == "high"
    assert after_stop.allow_workspace_write is True
    assert after_stop.allow_network is True

    permanently_locked_changes = (
        {"language": "ru"},
        {"initial_prompt": "Too late"},
        {"action_preset_id": None},
        {"agent_provider": "codex"},
        {"requested_agent_cwd": str(tmp_path)},
    )
    for changes in permanently_locked_changes:
        with pytest.raises(ServiceError) as locked_edit:
            service.update(session.id, changes)
        assert locked_edit.value.code == "session_already_started"

    database.dispose()


@pytest.mark.integration
def test_rest_snapshot_outbox_and_websocket_replay(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'api.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        created = client.post("/api/sessions", json={"title": "API session"})
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert client.post(f"/api/sessions/{session_id}/start").status_code == 200

        capture_service = CaptureService(app.state.database)
        assert (
            capture_service.update_source(source_status(), installation_id=str(uuid4()))
            == "applied"
        )
        assert (
            capture_service.process_caption(
                caption("utterance.upsert", sequence=2, revision=1, text="Live text")
            )
            == "applied"
        )
        assert (
            client.patch("/api/settings", json={"google_meet_own_name": "  иВАН  "}).status_code
            == 200
        )
        utterances = client.get(f"/api/sessions/{session_id}/utterances").json()
        assert utterances["items"][0]["text"] == "Live text"
        assert utterances["items"][0]["speaker_role"] == "self"

        snapshot = client.get("/api/snapshot").json()
        assert snapshot["sessions"][0]["id"] == session_id
        assert "utterances" not in snapshot
        detail = client.get(f"/api/sessions/{session_id}/detail").json()
        assert detail["utterances"]["items"][0]["revision"] == 1
        assert detail["utterances"]["items"][0]["speaker_role"] == "self"
        replay = client.get("/api/ui-events", params={"since": 0}).json()["events"]
        assert any(event["event_type"] == "utterance.created" for event in replay)

        websocket_headers = {
            "host": "127.0.0.1:38473",
            "origin": "http://127.0.0.1:38473",
        }
        with client.websocket_connect("/ws/ui?since=0", headers=websocket_headers) as websocket:
            first_event = websocket.receive_json()
            assert first_event["event_id"] == 1
            assert first_event["protocol_version"] == 1
        assert app.state.diagnostics.snapshot()["ui_clients_connected"] == 0
        with client.websocket_connect(
            "/ws/ui?since=999999", headers=websocket_headers
        ) as websocket:
            assert websocket.receive_json()["event_type"] == "resync_required"


@pytest.mark.integration
def test_session_prompt_and_working_directory_are_validated_before_start(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'session-editor.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )
    missing = tmp_path / "projects" / "new-project"
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        default_preset = client.get("/api/action-presets").json()[0]
        rejected = client.post(
            "/api/sessions",
            json={
                "title": "Missing directory",
                "language": "en",
                "initial_prompt": "Session-owned setup",
                "requested_agent_cwd": str(missing),
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "agent_cwd_missing"
        assert not missing.exists()

        created = client.post(
            "/api/sessions",
            json={
                "title": "Created directory",
                "language": "en",
                "initial_prompt": "Session-owned setup",
                "requested_agent_cwd": str(missing),
                "create_agent_cwd": True,
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert missing.is_dir()
        assert payload["requested_agent_cwd"] == str(missing.resolve())
        assert payload["initial_prompt"] == "Session-owned setup"
        assert payload["action_preset_id"] == default_preset["id"]

        updated_path = tmp_path / "projects" / "updated-project"
        rejected_update = client.patch(
            f"/api/sessions/{payload['id']}",
            json={"requested_agent_cwd": str(updated_path)},
        )
        assert rejected_update.status_code == 409
        assert rejected_update.json()["error"]["code"] == "agent_cwd_missing"
        updated = client.patch(
            f"/api/sessions/{payload['id']}",
            json={
                "requested_agent_cwd": str(updated_path),
                "create_agent_cwd": True,
                "initial_prompt": "Edited session setup",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["initial_prompt"] == "Edited session setup"
        assert updated_path.is_dir()

        assert client.post(f"/api/sessions/{payload['id']}/start").status_code == 200
        locked_path = tmp_path / "must-not-be-created"
        locked = client.patch(
            f"/api/sessions/{payload['id']}",
            json={
                "title": "Too late",
                "requested_agent_cwd": str(locked_path),
                "create_agent_cwd": True,
            },
        )
        assert locked.status_code == 409
        assert locked.json()["error"]["code"] == "session_running"
        assert not locked_path.exists()


@pytest.mark.integration
def test_french_prompts_and_global_permission_defaults_seed_new_sessions(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "ui_language": "en",
                "default_meeting_language": "en",
                "initial_prompts": {"ru": "Старый RU", "en": "Old EN"},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'permission-defaults.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=settings_path,
        agent_provider=FakeAgentProvider(),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        settings = client.get("/api/settings").json()
        assert settings["initial_prompts"]["fr"]
        assert settings["default_allow_workspace_write"] is False
        assert settings["default_allow_network"] is False

        configured = client.patch(
            "/api/settings",
            json={
                "ui_language": "fr",
                "default_meeting_language": "fr",
                "initial_prompts": {"fr": "Prompt français personnalisé"},
                "default_allow_workspace_write": True,
                "default_allow_network": True,
            },
        ).json()
        assert configured["ui_language"] == "fr"
        assert configured["initial_prompts"]["fr"] == "Prompt français personnalisé"

        inherited = client.post("/api/sessions", json={"title": "French defaults"}).json()
        assert inherited["language"] == "fr"
        assert inherited["initial_prompt"] == "Prompt français personnalisé"
        assert inherited["allow_workspace_write"] is True
        assert inherited["allow_network"] is True

        overridden = client.post(
            "/api/sessions",
            json={
                "title": "Explicit restrictions",
                "allow_workspace_write": False,
                "allow_network": False,
            },
        ).json()
        assert overridden["allow_workspace_write"] is False
        assert overridden["allow_network"] is False


@pytest.mark.integration
def test_global_theme_validation_persistence_and_settings_event(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'theme.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        assert client.get("/api/settings").json()["ui_theme"] == "dark"
        changed = client.patch("/api/settings", json={"ui_theme": "light"})
        assert changed.status_code == 200
        assert changed.json()["ui_theme"] == "light"
        assert client.patch("/api/settings", json={"ui_theme": "system"}).status_code == 422
        events = client.get("/api/ui-events", params={"since": 0}).json()["events"]
        event = next(item for item in events if item["event_type"] == "settings.changed")
        assert event["payload"] == {"ui_language": "en", "ui_theme": "light"}


@pytest.mark.integration
def test_global_initial_prompts_can_be_reset_to_defaults(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'prompt-reset.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        customized = client.patch(
            "/api/settings",
            json={
                "default_meeting_language": "fr",
                "initial_prompts": {
                    "ru": "Пользовательский RU",
                    "en": "Custom EN",
                    "fr": "FR personnalisé",
                },
            },
        ).json()

        reset = client.post("/api/settings/initial-prompts/reset")

        assert reset.status_code == 200
        payload = reset.json()
        assert payload["initial_prompts"] == DEFAULT_INITIAL_PROMPTS
        assert payload["initial_prompt_version"] == customized["initial_prompt_version"] + 1
        assert payload["default_meeting_language"] == "fr"


@pytest.mark.integration
def test_all_supported_session_languages_persist_and_unsupported_codes_fail(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'languages.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        for language in SUPPORTED_LANGUAGES:
            response = client.post(
                "/api/sessions",
                json={"title": f"Session {language}", "language": language},
            )
            assert response.status_code == 201
            payload = response.json()
            assert payload["language"] == language
            assert payload["initial_prompt"] == DEFAULT_INITIAL_PROMPTS[language]
            assert client.get(f"/api/sessions/{payload['id']}").json()["language"] == language

        for unsupported_language in ("pt", "pt-PT", "it"):
            assert (
                client.post(
                    "/api/sessions",
                    json={"title": "Unsupported", "language": unsupported_language},
                ).status_code
                == 422
            )
            assert (
                client.patch(
                    "/api/settings", json={"ui_language": unsupported_language}
                ).status_code
                == 422
            )


@pytest.mark.integration
def test_agent_provider_defaults_validation_lock_and_providers_api(tmp_path: Path) -> None:
    codex = FakeAgentProvider(chunks=("codex",))
    claude = FakeAgentProvider(chunks=("claude",))
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'providers.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=AgentProviderRegistry({"codex": codex, "claude": claude}),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        settings = client.get("/api/settings").json()
        assert settings["default_agent_provider"] == "codex"
        assert settings["default_agent_model"] is None
        assert settings["default_agent_reasoning_effort"] is None
        assert settings["claude_executable"] == "claude"
        inherited_codex = client.post("/api/sessions", json={"title": "Default Codex"}).json()
        assert inherited_codex["agent_provider"] == "codex"

        updated = client.patch(
            "/api/settings",
            json={
                "default_agent_provider": "claude",
                "default_agent_model": "fake-model",
                "default_agent_reasoning_effort": "high",
            },
        )
        assert updated.status_code == 200
        inherited_claude = client.post("/api/sessions", json={"title": "Default Claude"}).json()
        assert inherited_claude["agent_provider"] == "claude"
        assert inherited_claude["agent_model"] == "fake-model"
        assert inherited_claude["agent_reasoning_effort"] == "high"
        explicit_codex = client.post(
            "/api/sessions",
            json={
                "title": "Explicit Codex",
                "agent_provider": "codex",
                "agent_model": "fake-model",
                "agent_reasoning_effort": "low",
            },
        ).json()
        assert explicit_codex["agent_provider"] == "codex"
        assert explicit_codex["agent_model"] == "fake-model"
        assert explicit_codex["agent_reasoning_effort"] == "low"

        invalid_model = client.post(
            "/api/sessions",
            json={
                "title": "Invalid model",
                "agent_model": "unknown-model",
            },
        )
        assert invalid_model.status_code == 422
        assert invalid_model.json()["error"]["code"] == "invalid_agent_model"
        invalid_effort = client.patch(
            "/api/settings",
            json={
                "default_agent_model": "fake-model",
                "default_agent_reasoning_effort": "ultra",
            },
        )
        assert invalid_effort.status_code == 422
        assert invalid_effort.json()["error"]["code"] == "invalid_agent_reasoning_effort"

        for response in (
            client.post(
                "/api/sessions",
                json={"title": "Invalid", "agent_provider": "unknown"},
            ),
            client.patch(
                f"/api/sessions/{explicit_codex['id']}",
                json={"agent_provider": "unknown"},
            ),
            client.patch("/api/settings", json={"default_agent_provider": "unknown"}),
        ):
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_agent_provider"

        changed_before_start = client.patch(
            f"/api/sessions/{explicit_codex['id']}",
            json={
                "agent_provider": "claude",
                "agent_model": "fake-model",
                "agent_reasoning_effort": "low",
            },
        )
        assert changed_before_start.status_code == 200
        assert changed_before_start.json()["agent_provider"] == "claude"
        assert changed_before_start.json()["agent_model"] == "fake-model"
        assert changed_before_start.json()["agent_reasoning_effort"] == "low"
        assert client.post(f"/api/sessions/{explicit_codex['id']}/start").status_code == 200
        locked = client.patch(
            f"/api/sessions/{explicit_codex['id']}",
            json={"agent_provider": "codex"},
        )
        assert locked.status_code == 409
        assert locked.json()["error"]["code"] == "agent_provider_locked"
        model_while_running = client.patch(
            f"/api/sessions/{explicit_codex['id']}",
            json={"agent_reasoning_effort": "medium"},
        )
        assert model_while_running.status_code == 409
        assert model_while_running.json()["error"]["code"] == "session_running"
        assert client.post(f"/api/sessions/{explicit_codex['id']}/stop").status_code == 200
        model_after_stop = client.patch(
            f"/api/sessions/{explicit_codex['id']}",
            json={"agent_reasoning_effort": "medium"},
        )
        assert model_after_stop.status_code == 200
        assert model_after_stop.json()["agent_reasoning_effort"] == "medium"

        providers = client.get("/api/agent/providers").json()["providers"]
        assert [(item["id"], item["name"], item["status"]) for item in providers] == [
            ("codex", "Codex", "ready"),
            ("claude", "Claude Code", "ready"),
        ]
        assert all(item["models"][0]["id"] == "fake-model" for item in providers)
        diagnostics = client.get("/api/diagnostics").json()
        assert set(diagnostics["agents"]) == {"codex", "claude"}
        assert "codex" not in {key for key in diagnostics if key != "agents"}


@pytest.mark.integration
def test_unavailable_agent_executable_is_saved_and_reported(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'executable.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=AgentProviderRegistry(
            {"codex": FakeAgentProvider(), "claude": FakeAgentProvider()}
        ),
        app_paths=app_paths(tmp_path),
    )
    missing = str(tmp_path / "missing-codex")
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        updated = client.patch("/api/settings", json={"codex_executable": missing})
        assert updated.status_code == 200
        assert updated.json()["codex_executable"] == missing
        codex = next(
            provider
            for provider in client.get("/api/agent/providers").json()["providers"]
            if provider["id"] == "codex"
        )
        assert codex["status"] == "unavailable"
        assert codex["models"] == []


def test_fixture_serialization_is_bounded_and_safe() -> None:
    payload: dict[str, Any] = source_status().model_dump(mode="json")
    encoded = json.dumps(payload)
    assert "https://" not in encoded
    assert len(encoded) < 4096


@pytest.mark.integration
def test_session_update_segments_and_confirmed_delete(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'crud.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        created = client.post("/api/sessions", json={"title": "Before"}).json()
        session_id = created["id"]
        updated = client.patch(
            f"/api/sessions/{session_id}", json={"title": "After", "language": "en"}
        )
        assert updated.status_code == 200
        assert (updated.json()["title"], updated.json()["language"]) == ("After", "en")
        client.post(f"/api/sessions/{session_id}/start")
        client.post(f"/api/sessions/{session_id}/stop")
        assert client.get(f"/api/sessions/{session_id}/segments").json()[0]["sequence"] == 1
        assert (
            client.delete(f"/api/sessions/{session_id}", params={"confirm": "wrong"}).status_code
            == 400
        )
        assert (
            client.delete(f"/api/sessions/{session_id}", params={"confirm": session_id}).status_code
            == 204
        )


@pytest.mark.integration
def test_agent_streaming_is_visible_to_ui_test_client(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'stream.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(chunks=("streamed",), delay=0.03),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        session = client.post("/api/sessions", json={"title": "Streaming"}).json()
        client.post(f"/api/sessions/{session['id']}/start")
        with client.websocket_connect(
            "/ws/ui?since=0",
            headers={
                "host": "127.0.0.1:38473",
                "origin": "http://127.0.0.1:38473",
            },
        ) as websocket:
            events = [websocket.receive_json() for _ in range(8)]
        assert any(event["event_type"] == "agent.delta" for event in events)
        detail = client.get(f"/api/sessions/{session['id']}/detail").json()
        assert detail["agent_history"]["messages"][0]["text"] == "streamed"


@pytest.mark.integration
def test_settings_button_crud_and_run_snapshot_are_immutable(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'buttons.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(chunks=("answer",), delay=0.1),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        defaults = client.get("/api/buttons").json()
        assert [button["key"] for button in defaults] == [
            definition["key"] for definition in BUILTIN_ACTIONS
        ]
        generated = client.post(
            "/api/buttons",
            json={
                "label": "Generated key",
                "prompt_template": "Use a server-generated key",
                "context_strategy": "all",
                "context_value": 5,
                "hard_character_cap": 10_000,
            },
        ).json()
        assert generated["key"].startswith("action_")
        created = client.post(
            "/api/buttons",
            json={
                "key": "test_risks",
                "label": "Risks before edit",
                "prompt_template": "Find risks",
                "context_strategy": "all",
                "context_value": 5,
                "hard_character_cap": 10_000,
            },
        ).json()
        presets = client.get("/api/action-presets").json()
        assert len(presets) == len(BUILTIN_PRESETS)
        default_preset = next(preset for preset in presets if preset["is_default"])
        assert default_preset["name"] == "Default"
        assert default_preset["is_default"] is True
        default_action_ids = {button["key"]: button["id"] for button in defaults}
        assert default_preset["button_ids"] == [
            default_action_ids[key] for key in BUILTIN_PRESETS[0]["action_keys"]
        ]
        assert client.delete(f"/api/action-presets/{default_preset['id']}").status_code == 409

        empty_preset_response = client.post(
            "/api/action-presets", json={"name": "Release", "button_ids": []}
        )
        assert empty_preset_response.status_code == 201
        release_preset = empty_preset_response.json()
        assert release_preset["button_ids"] == []
        release_preset = client.patch(
            f"/api/action-presets/{release_preset['id']}",
            json={"name": "Release review", "button_ids": [created["id"], generated["id"]]},
        ).json()
        assert release_preset["name"] == "Release review"
        assert release_preset["button_ids"] == [created["id"], generated["id"]]
        assert (
            client.patch(
                f"/api/action-presets/{release_preset['id']}",
                json={"button_ids": [created["id"]] * 13},
            ).status_code
            == 422
        )
        settings = client.patch(
            "/api/settings",
            json={
                "initial_prompts": {"ru": "Новый начальный prompt"},
                "free_prompt_context_strategy": "last_utterances",
                "free_prompt_context_value": 7,
                "free_prompt_hard_character_cap": 12_000,
                "google_meet_own_name": "Иван",
                "microsoft_teams_own_name": "Alex Teams",
                "zoom_own_name": "Evgenii Gerasimenko",
            },
        ).json()
        assert settings["initial_prompt_version"] == 2
        assert settings["initial_prompts"]["en"]
        assert settings["free_prompt_context_strategy"] == "last_utterances"
        assert settings["free_prompt_context_value"] == 7
        assert settings["free_prompt_hard_character_cap"] == 12_000
        assert settings["google_meet_own_name"] == "Иван"
        assert settings["microsoft_teams_own_name"] == "Alex Teams"
        assert settings["zoom_own_name"] == "Evgenii Gerasimenko"

        missing_preset = client.post(
            "/api/sessions",
            json={"title": "Missing preset", "action_preset_id": str(uuid4())},
        )
        assert missing_preset.status_code == 404
        assert missing_preset.json()["error"]["code"] == "action_preset_not_found"

        session = client.post(
            "/api/sessions",
            json={"title": "Buttons", "action_preset_id": release_preset["id"]},
        ).json()
        assert session["action_preset_id"] == release_preset["id"]
        client.post(f"/api/sessions/{session['id']}/start")
        locked_preset = client.patch(
            f"/api/sessions/{session['id']}",
            json={"action_preset_id": default_preset["id"]},
        )
        assert locked_preset.status_code == 409
        assert locked_preset.json()["error"]["code"] == "session_running"
        run = client.post(
            f"/api/sessions/{session['id']}/agent-runs",
            json={"button_id": created["id"]},
        ).json()
        updated = client.patch(
            f"/api/buttons/{created['id']}",
            json={"label": "Risks after edit", "prompt_template": "Changed prompt"},
        ).json()
        assert updated["definition_version"] == 2

        persisted = next(
            item
            for item in client.get(f"/api/sessions/{session['id']}/agent-runs").json()
            if item["id"] == run["id"]
        )
        assert persisted["button_snapshot"]["label"] == "Risks before edit"
        assert "Find risks" in persisted["resolved_prompt"]
        assert "Changed prompt" not in persisted["resolved_prompt"]

        freeform_response = client.post(
            f"/api/sessions/{session['id']}/agent-runs",
            json={"prompt": "What should we clarify next?"},
        )
        assert freeform_response.status_code == 201
        freeform = freeform_response.json()
        assert freeform["button_id"] is None
        assert freeform["button_snapshot"]["kind"] == "freeform"
        assert freeform["context_strategy"] == "last_utterances"
        assert freeform["button_snapshot"]["context_value"] == 7
        assert freeform["button_snapshot"]["hard_character_cap"] == 12_000
        assert "What should we clarify next?" in freeform["resolved_prompt"]

        assert client.post(f"/api/sessions/{session['id']}/agent-runs", json={}).status_code == 422
        assert (
            client.post(
                f"/api/sessions/{session['id']}/agent-runs",
                json={"button_id": created["id"], "prompt": "Both"},
            ).status_code
            == 422
        )
        assert client.delete(f"/api/buttons/{created['id']}").status_code == 204
        release_after_delete = next(
            preset
            for preset in client.get("/api/action-presets").json()
            if preset["id"] == release_preset["id"]
        )
        assert release_after_delete["button_ids"] == [generated["id"]]
        assert client.delete(f"/api/action-presets/{release_preset['id']}").status_code == 204
        assert (
            client.get(f"/api/sessions/{session['id']}").json()["action_preset_id"]
            == default_preset["id"]
        )


@pytest.mark.integration
def test_source_switches_meet_to_teams_before_start_but_not_while_recording(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path / "source-switch.sqlite3")
    capture_service = CaptureService(database)
    installation = str(uuid4())

    def status(source_id: str, platform: str, sequence: int) -> SourceStatus:
        return SourceStatus.model_validate(
            {
                "type": "source.status",
                "protocol_version": 1,
                "event_id": str(uuid4()),
                "source_id": source_id,
                "client_seq": sequence,
                "platform": platform,
                "enabled": True,
                "captions_status": "on_empty",
                "speaker_detection": "available",
                "meeting_key": f"{platform}-meeting",
                "observed_at": NOW.isoformat(),
            }
        )

    assert (
        capture_service.update_source(
            status("meet", "google_meet", 1), installation_id=installation
        )
        == "applied"
    )
    assert (
        capture_service.update_source(
            status("teams", "microsoft_teams", 2), installation_id=installation
        )
        == "applied"
    )
    session = SessionService(database).create(title="Switch")
    started = SessionService(database).start(session.id)
    assert started.active_source_id == "teams"
    assert (
        capture_service.update_source(
            status("meet", "google_meet", 3), installation_id=installation
        )
        == "source_switch_rejected"
    )
    database.dispose()


@pytest.mark.integration
def test_same_tab_document_reload_rebinds_the_running_session(tmp_path: Path) -> None:
    database = make_database(tmp_path / "document-reload.sqlite3")
    capture_service = CaptureService(database)
    installation = str(uuid4())

    def document_status(source_id: str, document_id: str, meeting: str) -> SourceStatus:
        return SourceStatus.model_validate(
            {
                "type": "source.status",
                "protocol_version": 1,
                "event_id": str(uuid4()),
                "source_id": source_id,
                "tab_id": 17,
                "document_id": document_id,
                "client_seq": 1,
                "platform": "google_meet",
                "enabled": True,
                "captions_status": "on_empty",
                "meeting_key": meeting,
                "observed_at": NOW.isoformat(),
            }
        )

    first = document_status("installation:17:doc-1", "doc-1", "same-meeting")
    assert capture_service.update_source(first, installation_id=installation) == "applied"
    session = SessionService(database).create(title="Reload")
    SessionService(database).start(session.id)
    second = document_status("installation:17:doc-2", "doc-2", "same-meeting")
    assert capture_service.update_source(second, installation_id=installation) == "applied"
    assert SessionService(database).get(session.id).active_source_id == second.source_id
    different = document_status("installation:17:doc-3", "doc-3", "different-meeting")
    assert (
        capture_service.update_source(different, installation_id=installation)
        == "source_switch_rejected"
    )
    database.dispose()


@pytest.mark.integration
def test_long_session_snapshot_is_bounded_and_history_is_cursor_paginated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "long.sqlite3"
    # This database is reopened through application startup below, so initialize
    # it through the same migration path rather than creating an unversioned
    # metadata-only test schema.
    database = Database.from_path(database_path)
    database.migrate()
    session = SessionService(database).create(title="Long")
    SessionService(database).start(session.id, now=NOW)
    with database.transaction() as db:
        segment = db.scalar(
            select(RecordingSegmentRecord).where(RecordingSegmentRecord.session_id == session.id)
        )
        assert segment is not None
        db.add_all(
            [
                UtteranceRecord(
                    session_id=session.id,
                    segment_id=segment.id,
                    source_id="long-source",
                    utterance_id=f"long-{index}",
                    revision=1,
                    speaker="Speaker",
                    text=f"bounded secret transcript {index}",
                    final=True,
                    first_observed_at=NOW + timedelta(seconds=index),
                    last_observed_at=NOW + timedelta(seconds=index),
                    first_client_seq=index,
                    last_client_seq=index,
                )
                for index in range(5_100)
            ]
        )
        thread = AgentThreadRecord(
            session_id=session.id,
            provider="codex",
            external_thread_id="long-thread",
            init_prompt_snapshot="initial",
            status="ready",
        )
        db.add(thread)
        db.flush()
        runs = [
            AgentRunRecord(
                session_id=session.id,
                thread_id=thread.id,
                queue_sequence=index,
                status="completed",
                button_snapshot={},
                resolved_prompt="prompt",
                frozen_context="context",
                context_strategy="last_utterances",
                context_start=None,
                context_end=None,
                session_language="en",
                provider="codex",
                model=None,
                reasoning_effort=None,
                cwd=str(tmp_path),
                permissions_snapshot={},
                created_at=NOW + timedelta(seconds=index),
                completed_at=NOW + timedelta(seconds=index),
            )
            for index in range(60)
        ]
        db.add_all(runs)
        db.flush()
        db.add_all(
            [
                AgentMessageRecord(
                    run_id=run.id,
                    role="assistant",
                    message_type="answer",
                    text=f"answer {index}",
                    sequence=1,
                    status="complete",
                )
                for index, run in enumerate(runs)
            ]
        )
    database.dispose()

    app = create_app(
        database_url=f"sqlite:///{database_path}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
        app_paths=app_paths(tmp_path),
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        # Warm connections and statement caches before enforcing the CI budget.
        assert client.get("/api/snapshot").status_code == 200
        query_count = 0

        def count_query(*_: object) -> None:
            nonlocal query_count
            query_count += 1

        sqlalchemy_event.listen(app.state.database.engine, "before_cursor_execute", count_query)
        started = time.perf_counter()
        snapshot_response = client.get("/api/snapshot")
        snapshot_elapsed = time.perf_counter() - started
        snapshot_queries = query_count
        query_count = 0
        started = time.perf_counter()
        detail_response = client.get(f"/api/sessions/{session.id}/detail")
        detail_elapsed = time.perf_counter() - started
        detail_queries = query_count
        sqlalchemy_event.remove(app.state.database.engine, "before_cursor_execute", count_query)

        assert snapshot_response.status_code == 200
        assert detail_response.status_code == 200
        assert snapshot_elapsed < 2
        assert detail_elapsed < 2
        assert snapshot_queries <= 12
        assert detail_queries <= 16
        snapshot = snapshot_response.json()
        assert "utterances" not in snapshot
        assert "agent_history" not in snapshot
        detail = detail_response.json()
        assert detail["utterances"]["has_more"] is True
        assert len(detail["utterances"]["items"]) == 500
        assert detail["agent_history"]["has_more"] is True
        assert len(detail["agent_history"]["runs"]) == 50
        assert len(detail["agent_history"]["messages"]) == 50
        cursor = detail["utterances"]["next_cursor"]
        older = client.get(
            f"/api/sessions/{session.id}/utterances",
            params={"limit": 50, "cursor": cursor},
        ).json()
        assert len(older["items"]) == 50
        diagnostics = client.get("/api/diagnostics")
        assert diagnostics.status_code == 200
        assert "bounded secret transcript" not in diagnostics.text
