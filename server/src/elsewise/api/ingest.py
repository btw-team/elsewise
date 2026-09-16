import asyncio
import json
import time
from collections import deque
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from elsewise.api.security import safe_extension_origin
from elsewise.evidence import EvidenceBus
from elsewise.observability import RuntimeDiagnostics, log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import SessionRecord
from elsewise.protocol.models import (
    PROTOCOL_VERSION,
    ClientHello,
    EvidenceEmit,
    SourceCommandAck,
    SourceDiscovered,
    SourceHealth,
    parse_protocol_message,
)
from elsewise.services.errors import ServiceError
from elsewise.services.pairing import PairingService
from elsewise.services.sessions import session_payload
from elsewise.settings.config import SettingsStore
from elsewise.settings.limits import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_INGEST_EVENTS_PER_SECOND,
    MAX_INGEST_MESSAGE_BYTES,
)
from elsewise.sources.connections import BrowserConnectionRegistry
from elsewise.sources.manager import SourceManager
from elsewise.sources.projectors.evidence import EvidenceProjector


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
        "protocol_version": PROTOCOL_VERSION,
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
    if not safe_extension_origin(websocket.headers.get("origin", "")):
        await websocket.close(code=1008, reason="invalid_origin")
        return
    await websocket.accept()
    diagnostics = cast(RuntimeDiagnostics, websocket.app.state.diagnostics)
    diagnostics.connected("ingest")
    database = cast(Database, websocket.app.state.database)
    pairing = cast(PairingService, websocket.app.state.pairing)
    sources = cast(SourceManager, websocket.app.state.source_manager)
    connections = cast(BrowserConnectionRegistry, websocket.app.state.browser_connections)
    projector = EvidenceProjector(
        database,
        cast(EvidenceBus, websocket.app.state.evidence_bus),
        cast(SettingsStore, websocket.app.state.settings),
    )
    paired_client_id = ""
    connection_id = ""
    credential = ""
    recent_events: deque[float] = deque()
    command_tasks: set[asyncio.Task[str]] = set()
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
        except json.JSONDecodeError:
            hello_value = None
        if (
            isinstance(hello_value, dict)
            and hello_value.get("protocol_version") != PROTOCOL_VERSION
        ):
            await websocket.send_json(
                _error(
                    "incompatible_protocol",
                    f"Protocol version {PROTOCOL_VERSION} is required.",
                    recoverable=False,
                )
            )
            await websocket.close(code=1008)
            return
        try:
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
        client = pairing.verify(hello.credential)
        if client is None or client.installation_id != str(hello.installation_id):
            await websocket.send_json(
                _error("unauthorized", "The client credential is invalid.", recoverable=False)
            )
            await websocket.close(code=1008)
            return
        paired_client_id = client.id
        credential = hello.credential
        connection_id = connections.register(
            client.id,
            websocket.send_json,
            lambda code, reason: websocket.close(code=code, reason=reason),
        )
        with database.transaction() as db:
            current = db.scalar(
                select(SessionRecord).where(
                    SessionRecord.recording_status.in_(("starting", "running", "stopping"))
                )
            )
        await websocket.send_json(
            {
                "type": "server.hello",
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": [
                    "pairing_requests",
                    "daemon_source_control",
                    "normalized_evidence",
                ],
                "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
                "session": session_payload(current) if current else None,
            }
        )

        while True:
            raw = await websocket.receive_text()
            verified = pairing.verify(credential)
            if verified is None:
                await websocket.send_json(
                    _error("client_revoked", "The client was revoked.", recoverable=False)
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
                        select(SessionRecord).where(
                            SessionRecord.recording_status.in_(("starting", "running", "stopping"))
                        )
                    )
                await websocket.send_json(
                    {
                        "type": "heartbeat.ack",
                        "protocol_version": PROTOCOL_VERSION,
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
                        f"The message does not match protocol v{PROTOCOL_VERSION}.",
                        recoverable=False,
                        event_id=event_id,
                        client_seq=client_seq,
                    )
                )
                continue

            details: dict[str, Any] | None = None
            if isinstance(message, SourceDiscovered):
                try:
                    source_id, epoch_id = sources.discover(
                        message, paired_client_id=paired_client_id
                    )
                except ServiceError as exc:
                    ack_result = "rejected"
                    details = {"error_code": exc.code}
                else:
                    ack_result = "applied"
                    details = {"source_id": source_id, "source_epoch_id": epoch_id}
            elif isinstance(message, SourceHealth):
                ack_result = sources.update_health(message, paired_client_id=paired_client_id)
            elif isinstance(message, EvidenceEmit):
                ack_result = projector.process(message)
            elif isinstance(message, SourceCommandAck):
                connections.acknowledge(str(message.command_id), message.model_dump(mode="json"))
                continue
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
                    "protocol_version": PROTOCOL_VERSION,
                    "event_id": str(message.event_id),
                    "client_seq": message.client_seq,
                    "result": ack_result,
                    **({"reason": ack_result} if ack_result != "applied" else {}),
                    **({"details": details} if details is not None else {}),
                }
            )
            if isinstance(message, SourceDiscovered) and details is not None:
                epoch_id = details.get("source_epoch_id")
                if isinstance(epoch_id, str):
                    task = asyncio.create_task(sources.start_epoch(epoch_id))
                    command_tasks.add(task)
                    task.add_done_callback(command_tasks.discard)
    except WebSocketDisconnect:
        return
    finally:
        if paired_client_id and connections.unregister(paired_client_id, connection_id):
            sources.disconnect_client(paired_client_id)
        for task in command_tasks:
            task.cancel()
        diagnostics.disconnected("ingest")
