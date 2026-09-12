from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 2
Platform = Literal["google_meet", "microsoft_teams", "zoom", "synthetic"]
AckResult = Literal[
    "applied", "duplicate", "stale", "no_active_session", "source_not_bound", "rejected"
]


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairingRequest(StrictMessage):
    type: Literal["pairing.request"]
    protocol_version: Literal[2]
    nonce: str = Field(min_length=32, max_length=128)
    installation_id: UUID
    browser_family: Literal["chrome", "firefox"]
    display_name: str = Field(min_length=1, max_length=128)
    extension_version: str = Field(min_length=1, max_length=64)


class PairingCancel(StrictMessage):
    type: Literal["pairing.cancel"]
    protocol_version: Literal[2]


class PairingPending(StrictMessage):
    type: Literal["pairing.pending"]
    protocol_version: Literal[2]
    request_id: UUID
    expires_at: datetime


class PairingApproved(StrictMessage):
    type: Literal["pairing.approved"]
    protocol_version: Literal[2]
    request_id: UUID
    client_id: UUID
    credential: str = Field(min_length=48, max_length=256)


class PairingResult(StrictMessage):
    protocol_version: Literal[2]
    request_id: UUID


class PairingDenied(PairingResult):
    type: Literal["pairing.denied"]


class PairingExpired(PairingResult):
    type: Literal["pairing.expired"]


class PairingCancelled(PairingResult):
    type: Literal["pairing.cancelled"]


class PairingError(StrictMessage):
    type: Literal["pairing.error"]
    protocol_version: Literal[2]
    code: str = Field(min_length=1, max_length=128)


class ClientHello(StrictMessage):
    type: Literal["client.hello"]
    protocol_version: Literal[2]
    role: Literal["extension"]
    credential: str = Field(min_length=48, max_length=256)
    installation_id: UUID
    extension_version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=32)


class ServerHello(StrictMessage):
    type: Literal["server.hello"]
    protocol_version: Literal[2]
    capabilities: list[str] = Field(max_length=32)
    heartbeat_interval_seconds: int = Field(ge=1, le=300)
    session: dict[str, Any] | None = None


class Heartbeat(StrictMessage):
    type: Literal["heartbeat"]
    protocol_version: Literal[2]


class HeartbeatAck(StrictMessage):
    type: Literal["heartbeat.ack"]
    protocol_version: Literal[2]
    session: dict[str, Any] | None = None


class SourceDiscovered(StrictMessage):
    type: Literal["source.discovered"]
    protocol_version: Literal[2]
    event_id: UUID
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    tab_instance_id: str = Field(min_length=1, max_length=128)
    producer_epoch_id: str = Field(min_length=1, max_length=128)
    platform: Platform
    activity_key: str | None = Field(default=None, min_length=1, max_length=256)
    driver_id: str = Field(default="browser_captions", min_length=1, max_length=128)
    driver_version: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(max_length=32)
    health_status: Literal["available", "waiting", "degraded", "unavailable", "failed"]
    error_code: str | None = Field(default=None, max_length=128)
    observed_at: datetime


class SourceHealth(StrictMessage):
    type: Literal["source.health"]
    protocol_version: Literal[2]
    event_id: UUID
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    source_id: UUID
    source_epoch_id: UUID | None = None
    health_status: Literal["available", "waiting", "degraded", "unavailable", "failed"]
    error_code: str | None = Field(default=None, max_length=128)
    dropped_event_count: int = Field(default=0, ge=0)
    observed_at: datetime


class CaptionEvidence(StrictMessage):
    protocol_version: Literal[2]
    event_id: UUID
    source_id: UUID
    source_epoch_id: UUID
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    utterance_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, le=2_147_483_647)
    speaker: str | None = Field(default=None, max_length=512)
    text: str = Field(min_length=1, max_length=20_000)
    session_offset_us: int = Field(ge=0, le=9_223_372_036_854_775_807)
    source_time_us: int | None = Field(default=None, ge=0, le=9_223_372_036_854_775_807)


class CaptionUpsert(CaptionEvidence):
    type: Literal["caption.upsert"]


class CaptionFinalize(CaptionEvidence):
    type: Literal["caption.finalize"]


class EventAck(StrictMessage):
    type: Literal["event.ack"]
    protocol_version: Literal[2]
    event_id: UUID
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    result: AckResult
    reason: str | None = Field(default=None, max_length=1024)
    details: dict[str, Any] | None = None


class SourceCommand(StrictMessage):
    protocol_version: Literal[2]
    command_id: UUID
    source_id: UUID
    source_epoch_id: UUID
    tab_instance_id: str = Field(min_length=1, max_length=128)
    session_id: UUID
    segment_id: UUID
    deadline_ms: int = Field(ge=1, le=30_000)


class SourceStart(SourceCommand):
    type: Literal["source.start"]


class SourceStop(SourceCommand):
    type: Literal["source.stop"]


class SourceCommandAck(StrictMessage):
    type: Literal["source.command_ack"]
    protocol_version: Literal[2]
    command_id: UUID
    source_id: UUID
    source_epoch_id: UUID
    result: Literal["started", "finalized", "failed"]
    error_code: str | None = Field(default=None, max_length=128)


class UiEvent(StrictMessage):
    type: Literal["ui.event"]
    protocol_version: Literal[2]
    event_id: int = Field(ge=1, le=9_007_199_254_740_991)
    event_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str | None = Field(default=None, max_length=256)
    created_at: datetime
    payload: dict[str, Any]


class ProtocolError(StrictMessage):
    type: Literal["protocol.error"]
    protocol_version: Literal[2]
    event_id: UUID | None = None
    code: Literal[
        "invalid_json",
        "invalid_message",
        "incompatible_protocol",
        "unauthorized",
        "client_revoked",
        "hello_required",
        "unknown_message_type",
        "message_too_large",
        "rate_limited",
        "source_not_bound",
        "internal_error",
    ]
    message: str = Field(min_length=1, max_length=1024)
    recoverable: bool
    details: dict[str, Any] | None = None


ProtocolMessage = Annotated[
    PairingRequest
    | PairingCancel
    | PairingPending
    | PairingApproved
    | PairingDenied
    | PairingExpired
    | PairingCancelled
    | PairingError
    | ClientHello
    | ServerHello
    | Heartbeat
    | HeartbeatAck
    | SourceDiscovered
    | SourceHealth
    | CaptionUpsert
    | CaptionFinalize
    | EventAck
    | SourceStart
    | SourceStop
    | SourceCommandAck
    | UiEvent
    | ProtocolError,
    Field(discriminator="type"),
]
_protocol_adapter: TypeAdapter[ProtocolMessage] = TypeAdapter(ProtocolMessage)


def parse_protocol_message(value: object) -> ProtocolMessage:
    if isinstance(value, dict) and isinstance(value.get("type"), str):
        from elsewise.protocol.schemas import validate_schema

        validate_schema(value["type"], value)
    return _protocol_adapter.validate_python(value)
