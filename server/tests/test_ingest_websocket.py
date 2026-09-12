from pathlib import Path
from uuid import uuid4

import pytest
from elsewise.agents.fake import FakeAgentProvider
from elsewise.main import create_app
from elsewise.services.pairing import PairingService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'ingest.sqlite3'}",
        settings_path=tmp_path / "settings.json",
        agent_provider=FakeAgentProvider(),
    )


def paired_credential(app: FastAPI) -> tuple[str, str, str]:
    installation_id = str(uuid4())
    nonce = "n" * 64
    pairing: PairingService = app.state.pairing
    request = pairing.create_request(
        installation_id=installation_id,
        browser_family="chrome",
        display_name="Test Chrome",
        extension_version="2.0.0",
        nonce=nonce,
    )
    client = pairing.approve(request.id)
    delivery = pairing.take_delivery(request.id, nonce)
    assert delivery is not None
    return installation_id, client.id, delivery.credential


def hello(installation_id: str, credential: str) -> dict[str, object]:
    return {
        "type": "client.hello",
        "protocol_version": 2,
        "role": "extension",
        "credential": credential,
        "installation_id": installation_id,
        "extension_version": "2.0.0",
        "capabilities": [
            "pairing_requests",
            "daemon_source_control",
            "normalized_evidence",
        ],
    }


def discovered(client_seq: int = 1) -> dict[str, object]:
    return {
        "type": "source.discovered",
        "protocol_version": 2,
        "event_id": str(uuid4()),
        "client_seq": client_seq,
        "tab_instance_id": "tab-runtime-1",
        "producer_epoch_id": "producer-1",
        "platform": "synthetic",
        "activity_key": "opaque-activity",
        "driver_id": "synthetic_captions",
        "driver_version": "2.0.0",
        "capabilities": [
            "captions",
            "daemon_source_control",
            "normalized_evidence",
        ],
        "health_status": "available",
        "observed_at": "2026-08-13T12:00:00.000Z",
    }


def caption(source_id: str, epoch_id: str, event_id: str) -> dict[str, object]:
    return {
        "type": "caption.upsert",
        "protocol_version": 2,
        "event_id": event_id,
        "source_id": source_id,
        "source_epoch_id": epoch_id,
        "client_seq": 2,
        "utterance_id": "synthetic-1",
        "revision": 1,
        "speaker": "Speaker A",
        "text": "Synthetic caption",
        "session_offset_us": 1_000_000,
        "source_time_us": 500_000,
    }


@pytest.mark.integration
def test_pairing_approval_and_ingest_ack_duplicate(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        with client.websocket_connect(
            "/ws/pairing", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            nonce = "p" * 64
            websocket.send_json(
                {
                    "type": "pairing.request",
                    "protocol_version": 2,
                    "nonce": nonce,
                    "installation_id": str(uuid4()),
                    "browser_family": "chrome",
                    "display_name": "Work Chrome <script>",
                    "extension_version": "2.0.0",
                }
            )
            pending = websocket.receive_json()
            assert pending["type"] == "pairing.pending"
            paired = app.state.pairing.approve(pending["request_id"])
            approved = websocket.receive_json()
            assert approved["type"] == "pairing.approved"
            assert approved["client_id"] == paired.id
            installation_id = paired.installation_id
            credential = approved["credential"]

        session = client.post("/api/sessions", json={"title": "Synthetic"}).json()
        assert client.post(f"/api/sessions/{session['id']}/start").status_code == 200
        event_id = str(uuid4())
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(installation_id, credential))
            assert websocket.receive_json()["protocol_version"] == 2
            websocket.send_json(discovered())
            source_ack = websocket.receive_json()
            source_id = source_ack["details"]["source_id"]
            epoch_id = source_ack["details"]["source_epoch_id"]
            command = websocket.receive_json()
            assert command["type"] == "source.start"
            websocket.send_json(
                {
                    "type": "source.command_ack",
                    "protocol_version": 2,
                    "command_id": command["command_id"],
                    "source_id": source_id,
                    "source_epoch_id": epoch_id,
                    "result": "started",
                }
            )
            websocket.send_json(caption(source_id, epoch_id, event_id))
            assert websocket.receive_json()["result"] == "applied"
            websocket.send_json(caption(source_id, epoch_id, event_id))
            assert websocket.receive_json()["result"] == "duplicate"

        detail = client.get(f"/api/sessions/{session['id']}/detail").json()
        assert detail["utterances"]["items"][0]["text"] == "Synthetic caption"


@pytest.mark.integration
def test_ingest_rejects_bad_origin_credential_and_revoked_client(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        installation_id, client_id, credential = paired_credential(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/ingest", headers={"origin": "https://evil.invalid"}),
        ):
            pass
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(installation_id, f"{client_id}.{'x' * 43}"))
            assert websocket.receive_json()["code"] == "unauthorized"
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(installation_id, credential))
            assert websocket.receive_json()["type"] == "server.hello"
            assert client.delete(f"/api/paired-clients/{client_id}").status_code == 200
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


@pytest.mark.integration
def test_ingest_requires_v2_hello_and_enforces_message_size(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        installation_id, _, credential = paired_credential(app)
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(discovered())
            assert websocket.receive_json()["code"] == "hello_required"
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            incompatible = hello(installation_id, credential)
            incompatible["protocol_version"] = 1
            websocket.send_json(incompatible)
            assert websocket.receive_json()["code"] == "incompatible_protocol"
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(installation_id, credential))
            websocket.receive_json()
            websocket.send_text("x" * 70_000)
            assert websocket.receive_json()["code"] == "message_too_large"


@pytest.mark.integration
def test_ingest_rate_limit_is_typed_and_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("elsewise.api.ingest.MAX_INGEST_EVENTS_PER_SECOND", 2)
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:38473") as client:
        installation_id, _, credential = paired_credential(app)
        with client.websocket_connect(
            "/ws/ingest", headers={"origin": EXTENSION_ORIGIN}
        ) as websocket:
            websocket.send_json(hello(installation_id, credential))
            websocket.receive_json()
            for sequence in (1, 2):
                websocket.send_json(discovered(sequence))
                assert websocket.receive_json()["type"] == "event.ack"
            websocket.send_json(discovered(3))
            error = websocket.receive_json()
            assert error["type"] == "protocol.error"
            assert error["protocol_version"] == 2
            assert error["code"] == "rate_limited"
            assert error["recoverable"] is True
