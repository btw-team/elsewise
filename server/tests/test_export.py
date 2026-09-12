from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from elsewise.agents.fake import FakeAgentProvider
from elsewise.exports import ExportService
from elsewise.main import create_app
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    AgentMessageRecord,
    AgentRunRecord,
    AgentThreadRecord,
    CaptureSourceRecord,
    PairedClientRecord,
    RecordingSegmentRecord,
    SourceEpochRecord,
    UtteranceRecord,
)
from elsewise.protocol.models import CaptionUpsert
from elsewise.services.sessions import SessionService
from elsewise.settings.paths import AppPaths
from elsewise.sources.projectors.captions import CaptionProjector
from fastapi.testclient import TestClient
from sqlalchemy import select

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_markdown_export_is_deterministic_partial_safe_and_excludes_frozen_context(
    tmp_path: Path,
) -> None:
    database = Database.from_path(tmp_path / "export.sqlite3")
    database.create_schema()
    sessions = SessionService(database)
    session = sessions.create(title="<Unsafe & title>", description="Description", language="en")
    sessions.start(session.id, now=NOW)
    with database.transaction() as db:
        segment = db.scalar(select(RecordingSegmentRecord))
        assert segment is not None
        client = PairedClientRecord(
            installation_id=str(uuid4()),
            browser_family="chrome",
            display_name="Test Chrome",
            credential_digest="0" * 64,
        )
        db.add(client)
        db.flush()
        source = CaptureSourceRecord(
            paired_client_id=client.id,
            platform="google_meet",
            driver_id="google_meet_captions",
            driver_version="2.0.0",
            tab_instance_id="tab-1",
            capabilities=["captions"],
        )
        db.add(source)
        db.flush()
        epoch = SourceEpochRecord(
            source_id=source.id,
            session_id=session.id,
            segment_id=segment.id,
            producer_epoch_id="producer-1",
            state="running",
        )
        db.add(epoch)
        db.flush()
        source_id, epoch_id = source.id, epoch.id
    CaptionProjector(database).process(
        CaptionUpsert.model_validate(
            {
                "type": "caption.upsert",
                "protocol_version": 2,
                "event_id": str(uuid4()),
                "source_id": source_id,
                "source_epoch_id": epoch_id,
                "client_seq": 2,
                "utterance_id": "u-1",
                "revision": 1,
                "speaker": "Speaker <A>",
                "text": '<img src=x onerror="alert(1)"> text',
                "session_offset_us": 1_000,
            }
        )
    )
    with database.transaction() as db:
        thread = AgentThreadRecord(
            session_id=session.id,
            init_prompt_snapshot="initial",
            status="ready",
        )
        db.add(thread)
        db.flush()
        run = AgentRunRecord(
            session_id=session.id,
            thread_id=thread.id,
            queue_sequence=1,
            status="completed",
            button_snapshot={"label": "Summary"},
            resolved_prompt="Actual prompt",
            frozen_context="MUST_NOT_BE_DUPLICATED",
            context_strategy="all",
            context_start="u-1",
            context_end="u-1",
            session_language="en",
            provider="codex",
            cwd=str(tmp_path),
            permissions_snapshot={"allow_network": False},
            completed_at=NOW,
        )
        db.add(run)
        db.flush()
        db.add(
            AgentMessageRecord(
                run_id=run.id,
                role="assistant",
                message_type="answer",
                text="Final answer",
                sequence=1,
                status="completed",
            )
        )

    service = ExportService(database, tmp_path / "exports")
    first = service.export(session.id)
    captions = first.captions_path.read_text(encoding="utf-8")
    agent = first.agent_path.read_text(encoding="utf-8")
    assert "[partial]" in captions
    assert "&lt;img" in captions and "<img" not in captions
    assert "Recording started" in captions
    assert "Actual prompt" in agent and "Final answer" in agent
    assert "MUST_NOT_BE_DUPLICATED" not in agent
    before = (captions, agent)
    service.export(session.id)
    assert before == (
        first.captions_path.read_text(encoding="utf-8"),
        first.agent_path.read_text(encoding="utf-8"),
    )

    sessions.stop(session.id, now=NOW)
    service.export(session.id)
    stopped_captions = first.captions_path.read_text(encoding="utf-8")
    assert "[partial]" not in stopped_captions
    with database.transaction() as db:
        utterance = db.scalar(select(UtteranceRecord))
        assert utterance is not None and utterance.final is True
    database.dispose()


def test_export_cleanup_removes_only_the_exact_session_directory(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "cleanup.sqlite3")
    database.create_schema()
    session = SessionService(database).create(title="Cleanup")
    root = tmp_path / "exports"
    selected = root / session.id
    other = root / str(uuid4())
    selected.mkdir(parents=True)
    other.mkdir()
    (selected / "captions.md").write_text("selected", encoding="utf-8")
    (other / "keep.txt").write_text("keep", encoding="utf-8")

    ExportService(database, root).cleanup(session.id)

    assert not selected.exists()
    assert (other / "keep.txt").read_text(encoding="utf-8") == "keep"
    database.dispose()


def test_export_api_and_permanent_delete_remove_only_selected_exports(tmp_path: Path) -> None:
    paths = AppPaths(
        data=tmp_path,
        config=tmp_path / "config",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        database=tmp_path / "api.sqlite3",
        exports=tmp_path / "exports",
        diagnostics=tmp_path / "diagnostics",
        agent_empty_cwd=tmp_path / "runtime" / "agent-empty-cwd",
    )
    app = create_app(
        database_url=f"sqlite:///{paths.database}",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
        app_paths=paths,
    )
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        selected = client.post("/api/sessions", json={"title": "Selected"}).json()
        other = client.post("/api/sessions", json={"title": "Other"}).json()
        exported = client.post(f"/api/sessions/{selected['id']}/export")
        assert exported.status_code == 200
        selected_directory = Path(exported.json()["directory"])
        other_directory = paths.exports / other["id"]
        other_directory.mkdir(parents=True)
        (other_directory / "keep.txt").write_text("keep", encoding="utf-8")

        deleted = client.delete(
            f"/api/sessions/{selected['id']}", params={"confirm": selected["id"]}
        )
        assert deleted.status_code == 204
        assert not selected_directory.exists()
        assert (other_directory / "keep.txt").read_text(encoding="utf-8") == "keep"
