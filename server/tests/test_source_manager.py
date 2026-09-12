import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    PairedClientRecord,
    SessionRecord,
    SourceEpochRecord,
    UtteranceRecord,
)
from elsewise.protocol.models import CaptionFinalize, CaptionUpsert, SourceDiscovered
from elsewise.services.session_controller import SessionController
from elsewise.services.sessions import SessionService
from elsewise.services.transitions import TransitionExecutor
from elsewise.sources.connections import BrowserConnectionRegistry
from elsewise.sources.manager import SourceManager
from elsewise.sources.projectors.captions import CaptionProjector
from sqlalchemy import select


def database_at(path: Path) -> Database:
    database = Database.from_path(path)
    database.create_schema()
    return database


def add_client(database: Database, installation: str = "installation-1") -> str:
    with database.transaction() as db:
        client = PairedClientRecord(
            installation_id=installation,
            browser_family="chrome",
            display_name="Test Chrome",
            credential_digest="0" * 64,
        )
        db.add(client)
        db.flush()
        return client.id


def discovered(
    *,
    tab: str,
    producer: str = "producer-1",
    activity: str = "activity-1",
) -> SourceDiscovered:
    return SourceDiscovered.model_validate(
        {
            "type": "source.discovered",
            "protocol_version": 2,
            "event_id": str(uuid4()),
            "client_seq": 1,
            "tab_instance_id": tab,
            "producer_epoch_id": producer,
            "platform": "synthetic",
            "activity_key": activity,
            "driver_id": "synthetic_captions",
            "driver_version": "2",
            "capabilities": [
                "captions",
                "daemon_source_control",
                "normalized_evidence",
            ],
            "health_status": "available",
            "observed_at": "2026-09-12T12:00:00Z",
        }
    )


def register_sender(
    registry: BrowserConnectionRegistry,
    client_id: str,
    commands: list[dict[str, Any]],
) -> None:
    async def send(payload: dict[str, Any]) -> None:
        commands.append(payload)
        registry.acknowledge(
            str(payload["command_id"]),
            {"result": "started" if payload["type"] == "source.start" else "finalized"},
        )

    async def close(_: int, __: str) -> None:
        return None

    registry.register(client_id, send, close)


@pytest.mark.asyncio
async def test_multiple_sources_wait_for_selection_and_switch_stops_old_epoch(
    tmp_path: Path,
) -> None:
    database = database_at(tmp_path / "sources.sqlite3")
    client_id = add_client(database)
    connections = BrowserConnectionRegistry()
    commands: list[dict[str, Any]] = []
    register_sender(connections, client_id, commands)
    sources = SourceManager(database, connections)
    first_id, _ = sources.discover(discovered(tab="tab-1"), paired_client_id=client_id)
    second_id, _ = sources.discover(
        discovered(tab="tab-2", activity="activity-2"), paired_client_id=client_id
    )
    session = SessionService(database).create(title="Multiple sources")
    controller = SessionController(database, sources, TransitionExecutor())

    started = await controller.start(session.id)
    assert started.selected_source_id is None
    assert started.source_status == "waiting_for_source"
    assert commands == []

    selected = await controller.select_source(session.id, first_id)
    assert selected.selected_source_id == first_id
    assert [item["type"] for item in commands] == ["source.start"]
    same = await controller.select_source(session.id, first_id)
    assert same.selected_source_id == first_id
    assert [item["type"] for item in commands] == ["source.start"]

    switched = await controller.select_source(session.id, second_id)
    assert switched.selected_source_id == second_id
    assert [item["type"] for item in commands] == [
        "source.start",
        "source.stop",
        "source.start",
    ]
    with database.transaction() as db:
        epochs = list(
            db.scalars(select(SourceEpochRecord).where(SourceEpochRecord.session_id == session.id))
        )
        old = next(item for item in epochs if item.source_id == first_id)
        assert old.state == "stopped"
        assert old.end_reason == "source_switched"
    database.dispose()


@pytest.mark.asyncio
async def test_reconnect_reuses_epoch_and_producer_restart_creates_a_new_epoch(
    tmp_path: Path,
) -> None:
    database = database_at(tmp_path / "reconnect.sqlite3")
    client_id = add_client(database)
    connections = BrowserConnectionRegistry()
    commands: list[dict[str, Any]] = []
    register_sender(connections, client_id, commands)
    sources = SourceManager(database, connections)
    session = SessionService(database).create(title="Reconnect")
    await SessionController(database, sources, TransitionExecutor()).start(session.id)

    source_id, epoch_id = sources.discover(discovered(tab="tab-1"), paired_client_id=client_id)
    assert epoch_id is not None
    sources.disconnect_client(client_id)
    reconnected_source, reconnected_epoch = sources.discover(
        discovered(tab="tab-1"), paired_client_id=client_id
    )
    assert (reconnected_source, reconnected_epoch) == (source_id, epoch_id)
    with database.transaction() as db:
        epoch = db.get(SourceEpochRecord, epoch_id)
        assert epoch is not None and epoch.reconnect_count == 1
        running = db.get(SessionRecord, session.id)
        assert running is not None and running.recording_status == "running"

    _, restarted_epoch = sources.discover(
        discovered(tab="tab-1", producer="producer-2"), paired_client_id=client_id
    )
    assert restarted_epoch is not None and restarted_epoch != epoch_id
    with database.transaction() as db:
        old = db.get(SourceEpochRecord, epoch_id)
        assert old is not None
        assert old.state == "stopped"
        assert old.end_reason == "producer_restart"
    database.dispose()


@pytest.mark.asyncio
async def test_activity_change_creates_source_and_requires_new_selection(tmp_path: Path) -> None:
    database = database_at(tmp_path / "activity-change.sqlite3")
    client_id = add_client(database)
    sources = SourceManager(database)
    session = SessionService(database).create(title="Activity change")
    await SessionController(database, sources, TransitionExecutor()).start(session.id)
    first_source, first_epoch = sources.discover(
        discovered(tab="tab-1", activity="activity-1"), paired_client_id=client_id
    )
    assert first_epoch is not None

    next_source, next_epoch = sources.discover(
        discovered(tab="tab-1", activity="activity-2"), paired_client_id=client_id
    )
    assert next_source != first_source
    assert next_epoch is None
    current = SessionService(database).get(session.id)
    assert current.recording_status == "running"
    assert current.selected_source_id == first_source
    assert current.source_status == "waiting_for_source"
    with database.transaction() as db:
        old = db.get(SourceEpochRecord, first_epoch)
        assert old is not None
        assert old.state == "stopped"
        assert old.end_reason == "activity_changed"
    database.dispose()


@pytest.mark.asyncio
async def test_failed_start_degrades_source_without_stopping_session(tmp_path: Path) -> None:
    database = database_at(tmp_path / "failed-start.sqlite3")
    client_id = add_client(database)
    connections = BrowserConnectionRegistry()

    async def fail(payload: dict[str, Any]) -> None:
        connections.acknowledge(
            str(payload["command_id"]),
            {"result": "failed", "error_code": "producer_error"},
        )

    async def close(_: int, __: str) -> None:
        return None

    connections.register(client_id, fail, close)
    sources = SourceManager(database, connections)
    sources.discover(discovered(tab="tab-1"), paired_client_id=client_id)
    session = SessionService(database).create(title="Failed source")
    controller = SessionController(database, sources, TransitionExecutor())
    result = await controller.start(session.id)
    assert result.recording_status == "running"
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert SessionService(database).get(session.id).source_status == "degraded"
    database.dispose()


@pytest.mark.asyncio
async def test_session_start_does_not_wait_for_source_ack(tmp_path: Path) -> None:
    database = database_at(tmp_path / "delayed-start.sqlite3")
    client_id = add_client(database)
    connections = BrowserConnectionRegistry()
    command_sent = asyncio.Event()

    async def delayed(_: dict[str, Any]) -> None:
        command_sent.set()

    async def close(_: int, __: str) -> None:
        return None

    connections.register(client_id, delayed, close)
    sources = SourceManager(database, connections)
    sources.discover(discovered(tab="tab-1"), paired_client_id=client_id)
    session = SessionService(database).create(title="Non-blocking start")
    controller = SessionController(database, sources, TransitionExecutor())

    result = await asyncio.wait_for(controller.start(session.id), timeout=0.1)
    assert result.recording_status == "running"
    await asyncio.wait_for(command_sent.wait(), timeout=0.1)
    await controller.close()
    database.dispose()


@pytest.mark.asyncio
async def test_stale_disconnect_does_not_unregister_reconnected_client() -> None:
    registry = BrowserConnectionRegistry()
    deliveries: list[str] = []

    async def first_sender(_: dict[str, Any]) -> None:
        deliveries.append("first")

    async def second_sender(payload: dict[str, Any]) -> None:
        deliveries.append("second")
        registry.acknowledge(str(payload["command_id"]), {"result": "started"})

    async def close(_: int, __: str) -> None:
        return None

    first_connection = registry.register("client", first_sender, close)
    registry.register("client", second_sender, close)
    assert registry.unregister("client", first_connection) is False
    result = await registry.command("client", {"type": "source.start"}, timeout_seconds=0.1)
    assert result == {"result": "started"}
    assert deliveries == ["second"]


def test_source_clock_mapping_accepts_only_pre_boundary_evidence(tmp_path: Path) -> None:
    database = database_at(tmp_path / "clock.sqlite3")
    client_id = add_client(database)
    sessions = SessionService(database)
    session = sessions.create(title="Clock mapping")
    sessions.start(session.id)
    sources = SourceManager(database)
    source_id, epoch_id = sources.discover(discovered(tab="tab-1"), paired_client_id=client_id)
    assert epoch_id is not None
    with database.transaction() as db:
        record = db.get(SessionRecord, session.id)
        assert record is not None
        record.monotonic_origin_ns = 1_000_000

    daemon_time = 1_010
    projector = CaptionProjector(database, monotonic_us=lambda: daemon_time)

    def evidence(
        model: type[CaptionUpsert] | type[CaptionFinalize],
        *,
        utterance_id: str,
        revision: int,
        source_time_us: int,
    ) -> CaptionUpsert | CaptionFinalize:
        return model.model_validate(
            {
                "type": "caption.upsert" if model is CaptionUpsert else "caption.finalize",
                "protocol_version": 2,
                "event_id": str(uuid4()),
                "source_id": source_id,
                "source_epoch_id": epoch_id,
                "client_seq": revision,
                "utterance_id": utterance_id,
                "revision": revision,
                "text": "caption",
                "session_offset_us": 999_999,
                "source_time_us": source_time_us,
            }
        )

    assert (
        projector.process(
            evidence(CaptionUpsert, utterance_id="partial", revision=1, source_time_us=10)
        )
        == "applied"
    )
    with database.transaction() as db:
        record = db.get(SessionRecord, session.id)
        assert record is not None
        record.recording_status = "stopping"
        record.stop_boundary_offset_us = 100

    daemon_time = 1_200
    assert (
        projector.process(
            evidence(CaptionFinalize, utterance_id="partial", revision=2, source_time_us=100)
        )
        == "applied"
    )
    assert (
        projector.process(
            evidence(CaptionUpsert, utterance_id="late", revision=1, source_time_us=101)
        )
        == "rejected"
    )
    with database.transaction() as db:
        stored = db.scalar(select(SourceEpochRecord).where(SourceEpochRecord.id == epoch_id))
        assert stored is not None
        utterance = db.scalar(
            select(UtteranceRecord).where(UtteranceRecord.utterance_id == "partial")
        )
        assert utterance is not None
        assert utterance.first_session_offset_us == 10
        assert utterance.last_session_offset_us == 100
    database.dispose()
