from pathlib import Path
from uuid import uuid4

import pytest
from elsewise.agents.fake import FakeAgentProvider
from elsewise.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def hello(token: str) -> dict[str, object]:
    return {
        "type": "client.hello",
        "protocol_version": 1,
        "role": "extension",
        "token": token,
        "installation_id": str(uuid4()),
        "extension_version": "0.1.2",
    }


def source_status(
    *, source_id: str = "synthetic-source", client_seq: int = 1, enabled: bool = True
) -> dict[str, object]:
    return {
        "type": "source.status",
        "protocol_version": 1,
        "event_id": str(uuid4()),
        "source_id": source_id,
        "client_seq": client_seq,
        "platform": "synthetic",
        "enabled": enabled,
        "captions_status": "on_empty" if enabled else "off",
        "speaker_detection": "available",
        "meeting_key": "harness",
        "observed_at": "2026-08-13T12:00:00.000Z",
    }


def upsert(event_id: str | None = None) -> dict[str, object]:
    return {
        "type": "utterance.upsert",
        "protocol_version": 1,
        "event_id": event_id or str(uuid4()),
        "source_id": "synthetic-source",
        "client_seq": 2,
        "platform": "synthetic",
        "meeting_key": "harness",
        "utterance_id": "synthetic-1",
        "revision": 1,
        "speaker": "Speaker A",
        "text": "Synthetic caption",
        "observed_at": "2026-08-13T12:00:01.000Z",
    }


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'ingest.sqlite3'}",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )


@pytest.mark.integration
def test_pairing_origin_and_ingest_ack_duplicate(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        assert (
            client.post(
                "/api/sessions",
                json={"title": "Blocked"},
                headers={"origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        assert client.get("/api/health", headers={"host": "evil.invalid"}).status_code == 403
        assert (
            client.post(
                "/api/extension/pairing/regenerate",
                headers={"origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        pairing = client.post(
            "/api/extension/pairing/regenerate",
            headers={"origin": "http://127.0.0.1:38473"},
        )
        assert pairing.status_code == 200
        token = pairing.json()["token"]
        metadata = client.get("/api/extension/pairing").json()
        assert metadata["token"] == token
        assert token not in metadata["masked_token"]
        assert (tmp_path / "pairing.json").stat().st_mode & 0o777 == 0o600
        assert client.put("/api/extension/pairing", json={"token": "too-short"}).status_code == 422

        manual_token = "manual-pairing-token-value"
        updated = client.put(
            "/api/extension/pairing",
            json={"token": f"  {manual_token}  "},
        )
        assert updated.status_code == 200
        assert updated.json()["token"] == manual_token
        assert updated.json()["generation"] == metadata["generation"] + 1
        token = manual_token

        session = client.post("/api/sessions", json={"title": "Synthetic"}).json()
        client.post(f"/api/sessions/{session['id']}/start")

        event_id = str(uuid4())
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "server.hello"
            status = source_status()
            websocket.send_json(status)
            status_ack = websocket.receive_json()
            assert (status_ack["type"], status_ack["result"]) == ("event.ack", "applied")
            websocket.send_json(upsert(event_id))
            assert websocket.receive_json()["result"] == "applied"
            websocket.send_json(upsert(event_id))
            assert websocket.receive_json()["result"] == "duplicate"
            websocket.send_json(source_status(source_id="other-source", client_seq=3))
            rejected = websocket.receive_json()
            assert (rejected["result"], rejected["reason"]) == (
                "rejected",
                "source_switch_rejected",
            )
            websocket.send_json(source_status(client_seq=4, enabled=False))
            assert websocket.receive_json()["result"] == "applied"
            websocket.send_json({"type": "heartbeat", "protocol_version": 1})
            heartbeat = websocket.receive_json()
            assert heartbeat["type"] == "heartbeat.ack"
            assert heartbeat["session"]["id"] == session["id"]

        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/ws/ui?since=0",
                headers={
                    "host": "127.0.0.1:38473",
                    "origin": "https://evil.invalid",
                },
            ) as websocket,
        ):
            websocket.receive_json()

        snapshot = client.get("/api/snapshot").json()
        detail = client.get(f"/api/sessions/{session['id']}/detail").json()
        assert detail["utterances"]["items"][0]["text"] == "Synthetic caption"
        assert snapshot["sessions"][0]["capture_status"] == "waiting_for_source"


@pytest.mark.integration
def test_ingest_rejects_bad_origin_token_and_rotated_connection(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        token = client.post("/api/extension/pairing/regenerate").json()["token"]
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/ingest", headers={"origin": "https://evil.invalid"}),
        ):
            pass
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/ws/ingest",
                headers={"origin": f"{EXTENSION_ORIGIN}.evil"},
            ),
        ):
            pass

        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello("invalid-token-value"))
            assert websocket.receive_json()["code"] == "unauthorized"

        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "server.hello"
            client.post("/api/extension/pairing/regenerate")
            websocket.send_json({"type": "heartbeat", "protocol_version": 1})
            assert websocket.receive_json()["code"] == "unauthorized"


@pytest.mark.integration
def test_ingest_requires_hello_and_enforces_message_size(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        token = client.post("/api/extension/pairing/regenerate").json()["token"]
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(source_status())
            assert websocket.receive_json()["code"] == "hello_required"

        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(token))
            assert websocket.receive_json()["type"] == "server.hello"
            websocket.send_text("x" * 70_000)
            assert websocket.receive_json()["code"] == "message_too_large"


@pytest.mark.integration
def test_ingest_rate_limit_is_typed_and_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("elsewise.api.ingest.MAX_INGEST_EVENTS_PER_SECOND", 2)
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        token = client.post("/api/extension/pairing/regenerate").json()["token"]
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(token))
            websocket.receive_json()
            for sequence in (1, 2):
                websocket.send_json(source_status(client_seq=sequence))
                assert websocket.receive_json()["type"] == "event.ack"
            websocket.send_json(source_status(client_seq=3))
            error = websocket.receive_json()
            assert error == {
                "type": "protocol.error",
                "protocol_version": 1,
                "code": "rate_limited",
                "message": "Too many ingest events.",
                "recoverable": True,
                "event_id": error["event_id"],
                "client_seq": 3,
            }
