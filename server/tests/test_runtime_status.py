import os
from pathlib import Path
from typing import Any

from elsewise.agents.fake import FakeAgentProvider
from elsewise.agents.registry import AgentProviderRegistry
from elsewise.main import create_app
from elsewise.persistence.models import AgentRunRecord, AgentThreadRecord, SessionRecord
from elsewise.services.runtime_status import resolve_executable
from elsewise.settings.paths import AppPaths
from fastapi.testclient import TestClient


def app_paths(root: Path) -> AppPaths:
    data = root / "data"
    runtime = data / "runtime"
    return AppPaths(
        data=data,
        config=root / "config",
        cache=root / "cache",
        runtime=runtime,
        database=data / "elsewise.sqlite3",
        exports=data / "exports",
        diagnostics=data / "diagnostics",
        agent_empty_cwd=runtime / "agent-empty-cwd",
    )


def collect_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(collect_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(collect_keys(item) for item in value))
    return set()


def test_resolve_executable_honors_absolute_path(tmp_path: Path) -> None:
    executable = tmp_path / "agent tool"
    executable.write_text("", encoding="utf-8")

    assert resolve_executable(str(executable)) == str(executable.resolve())
    assert resolve_executable(str(tmp_path / "missing")) is None


def test_resolve_executable_uses_process_path(tmp_path: Path, monkeypatch: Any) -> None:
    executable = tmp_path / "test-agent"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")

    assert resolve_executable("test-agent") == str(executable.resolve())


def test_runtime_status_api_and_websocket_are_bounded(tmp_path: Path) -> None:
    paths = app_paths(tmp_path)
    app = create_app(
        database_url="sqlite://",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        app_paths=paths,
        agent_provider=AgentProviderRegistry(
            {"codex": FakeAgentProvider(), "claude": FakeAgentProvider()}
        ),
    )
    forbidden = {"utterances", "agent_messages", "transcript", "prompt", "text"}

    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        response = client.get("/api/runtime/status")
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {
            "server",
            "connections",
            "session",
            "source",
            "agent_work",
            "settings",
            "agents",
        }
        assert payload["session"] is None
        assert set(payload["agents"]) == {"codex", "claude"}
        assert forbidden.isdisjoint(collect_keys(payload))

        with app.state.database.transaction() as db:
            session = SessionRecord(title="Agent status")
            db.add(session)
            db.flush()
            thread = AgentThreadRecord(
                session_id=session.id,
                provider="codex",
                init_prompt_snapshot="Initial",
            )
            db.add(thread)
            db.flush()
            for sequence, status in enumerate(("starting", "streaming"), start=1):
                db.add(
                    AgentRunRecord(
                        session_id=session.id,
                        thread_id=thread.id,
                        queue_sequence=sequence,
                        status=status,
                        button_snapshot={},
                        resolved_prompt="Request",
                        frozen_context="",
                        context_strategy="initial",
                        session_language="en",
                        provider="codex",
                        cwd=str(tmp_path),
                        permissions_snapshot={},
                    )
                )
        assert client.get("/api/runtime/status").json()["agent_work"] == {
            "queued": 0,
            "running": 2,
            "draining": False,
        }

        with client.websocket_connect(
            "ws://127.0.0.1:38473/ws/runtime",
            headers={"origin": "http://127.0.0.1:38473"},
        ) as websocket:
            message = websocket.receive_json()
            assert message["type"] == "runtime.status"
            assert message["sequence"] == 1
            assert forbidden.isdisjoint(collect_keys(message["payload"]))

            app.state.diagnostics.connected("ui")
            changed = websocket.receive_json()
            assert changed["sequence"] == 2
            assert changed["payload"]["connections"]["web_gui"] == {
                "connected": True,
                "count": 1,
            }
            app.state.diagnostics.disconnected("ui")

    assert app.state.diagnostics.snapshot()["launcher_clients_connected"] == 0
