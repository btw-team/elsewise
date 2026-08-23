import json
import time
from collections import deque
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from elsewise.api.security import safe_extension_origin
from elsewise.observability import RuntimeDiagnostics, log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import SessionRecord
from elsewise.protocol.models import (
    ClientHello,
    SourceStatus,
    UtteranceFinalize,
    UtteranceUpsert,
    parse_protocol_message,
)
from elsewise.services.capture import CaptureService
from elsewise.services.sessions import session_payload
from elsewise.settings.config import SettingsStore
from elsewise.settings.limits import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_INGEST_EVENTS_PER_SECOND,
    MAX_INGEST_MESSAGE_BYTES,
)
from elsewise.settings.pairing import PairingManager


def _error(
    code: str,
    message: str,
    *,
    recoverable: bool,
    event_id: str | None = None,
    client_seq: int | None = None,
) -> dict[str, Any]:
    log_event("protocol.rejected", reason=code, recoverable=recoverable)
    return {
        "type": "protocol.error",
        "protocol_version": 1,
        "code": code,
        "message": message,
        "recoverable": recoverable,
        **({"event_id": event_id} if event_id else {}),
        **({"client_seq": client_seq} if client_seq is not None else {}),
    }


def _event_reference(payload: object) -> tuple[str | None, int | None]:
    if not isinstance(payload, dict):
        return None, None
    event_id = payload.get("event_id")
    client_seq = payload.get("client_seq")
    return (
        event_id if isinstance(event_id, str) else None,
        client_seq if isinstance(client_seq, int) else None,
    )


async def ingest_websocket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin", "")
    if not safe_extension_origin(origin):
        await websocket.close(code=1008, reason="invalid_origin")
        return
    await websocket.accept()
    diagnostics = cast(RuntimeDiagnostics, websocket.app.state.diagnostics)
    diagnostics.connected("ingest")
    database = cast(Database, websocket.app.state.database)
    pairing = cast(PairingManager, websocket.app.state.pairing)
    capture = CaptureService(database, cast(SettingsStore, websocket.app.state.settings))
    installation_id = ""
    recent_events: deque[float] = deque()
    try:
        raw = await websocket.receive_text()
        if len(raw.encode("utf-8")) > MAX_INGEST_MESSAGE_BYTES:
            await websocket.send_json(
                _error("message_too_large", "Message is too large.", recoverable=False)
            )
            await websocket.close(code=1009)
            return
        try:
            hello_value = json.loads(raw)
            hello = parse_protocol_message(hello_value)
        except Exception:
            await websocket.send_json(
                _error("hello_required", "A valid client.hello is required.", recoverable=False)
            )
            await websocket.close(code=1008)
            return
        if not isinstance(hello, ClientHello):
            await websocket.send_json(
                _error("hello_required", "client.hello must be the first frame.", recoverable=False)
            )
            await websocket.close(code=1008)
            return
        if not pairing.verify(hello.token):
            await websocket.send_json(
                _error("unauthorized", "The pairing token is invalid.", recoverable=False)
            )
            await websocket.close(code=1008)
            return
        installation_id = str(hello.installation_id)
        pairing_generation = pairing.metadata().generation
        with database.transaction() as db:
            current = db.scalar(
                select(SessionRecord).where(SessionRecord.recording_status == "running")
            )
        await websocket.send_json(
            {
                "type": "server.hello",
                "protocol_version": 1,
                "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
                "session": session_payload(current) if current else None,
            }
        )

        while True:
            raw = await websocket.receive_text()
            if pairing.metadata().generation != pairing_generation:
                await websocket.send_json(
                    _error("unauthorized", "The pairing token was regenerated.", recoverable=False)
                )
                await websocket.close(code=1008)
                return
            if len(raw.encode("utf-8")) > MAX_INGEST_MESSAGE_BYTES:
                try:
                    oversized_payload = json.loads(raw)
                except json.JSONDecodeError:
                    oversized_payload = None
                event_id, client_seq = _event_reference(oversized_payload)
                await websocket.send_json(
                    _error(
                        "message_too_large",
                        "Message is too large.",
                        recoverable=False,
                        event_id=event_id,
                        client_seq=client_seq,
                    )
                )
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    _error("invalid_json", "The frame is not valid JSON.", recoverable=True)
                )
                continue
            if payload.get("type") == "heartbeat":
                with database.transaction() as db:
                    current = db.scalar(
                        select(SessionRecord).where(SessionRecord.recording_status == "running")
                    )
                await websocket.send_json(
                    {
                        "type": "heartbeat.ack",
                        "protocol_version": 1,
                        "session": session_payload(current) if current else None,
                    }
                )
                continue
            now = time.monotonic()
            while recent_events and recent_events[0] < now - 1:
                recent_events.popleft()
            if len(recent_events) >= MAX_INGEST_EVENTS_PER_SECOND:
                event_id, client_seq = _event_reference(payload)
                await websocket.send_json(
                    _error(
                        "rate_limited",
                        "Too many ingest events.",
                        recoverable=True,
                        event_id=event_id,
                        client_seq=client_seq,
                    )
                )
                continue
            recent_events.append(now)
            try:
                message = parse_protocol_message(payload)
            except Exception:
                event_id, client_seq = _event_reference(payload)
                await websocket.send_json(
                    _error(
                        "invalid_message",
                        "The message does not match protocol v1.",
                        recoverable=False,
                        event_id=event_id,
                        client_seq=client_seq,
                    )
                )
                continue
            source_rejected = False
            if isinstance(message, SourceStatus):
                result = capture.update_source(message, installation_id=installation_id)
                source_rejected = result == "source_switch_rejected"
                ack_result = "rejected" if source_rejected else result
            elif isinstance(message, (UtteranceUpsert, UtteranceFinalize)):
                ack_result = capture.process_caption(message)
            else:
                event_id, client_seq = _event_reference(payload)
                await websocket.send_json(
                    _error(
                        "unknown_message_type",
                        "Message type is not accepted on ingest.",
                        recoverable=False,
                        event_id=event_id,
                        client_seq=client_seq,
                    )
                )
                continue
            await websocket.send_json(
                {
                    "type": "event.ack",
                    "protocol_version": 1,
                    "event_id": str(message.event_id),
                    "client_seq": message.client_seq,
                    "result": ack_result,
                    **({"reason": "source_switch_rejected"} if source_rejected else {}),
                }
            )
    except WebSocketDisconnect:
        return
    finally:
        diagnostics.disconnected("ingest")
