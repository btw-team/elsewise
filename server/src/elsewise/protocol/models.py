from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Platform = Literal["google_meet", "microsoft_teams", "zoom", "synthetic"]
AckResult = Literal[
    "applied",
    "duplicate",
    "stale",
    "no_active_session",
    "source_not_bound",
    "grace_finalize_applied",
    "rejected",
]


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientHello(StrictMessage):
    type: Literal["client.hello"]
    protocol_version: Literal[1]
    role: Literal["extension"]
    token: str = Field(min_length=16, max_length=4096)
    installation_id: UUID
    extension_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$",
    )


class SourceStatus(StrictMessage):
    type: Literal["source.status"]
    protocol_version: Literal[1]
    event_id: UUID
    source_id: str = Field(min_length=1, max_length=256)
    tab_id: int | None = Field(default=None, ge=0)
    document_id: str | None = Field(default=None, min_length=1, max_length=256)
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    platform: Platform
    enabled: bool
    captions_status: Literal["unknown", "off", "on_empty", "capturing", "unavailable", "error"]
    speaker_detection: Literal["unknown", "available", "unavailable"] | None = None
    meeting_key: str | None = Field(default=None, min_length=1, max_length=256)
    meeting_title: str | None = Field(default=None, max_length=512)
    last_caption_at: datetime | None = None
    observed_at: datetime
    diagnostic_code: str | None = Field(default=None, max_length=128)


class CaptionMessage(StrictMessage):
    protocol_version: Literal[1]
    event_id: UUID
    source_id: str = Field(min_length=1, max_length=256)
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    platform: Platform
    meeting_key: str = Field(min_length=1, max_length=256)
    utterance_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, le=2_147_483_647)
    speaker: str | None = Field(default=None, max_length=512)
    text: str = Field(min_length=1, max_length=20_000)
    observed_at: datetime


class UtteranceUpsert(CaptionMessage):
    type: Literal["utterance.upsert"]


class UtteranceFinalize(CaptionMessage):
    type: Literal["utterance.finalize"]


class EventAck(StrictMessage):
    type: Literal["event.ack"]
    protocol_version: Literal[1]
    event_id: UUID
    client_seq: int = Field(ge=0, le=9_007_199_254_740_991)
    result: AckResult
    reason: str | None = Field(default=None, max_length=1024)


class UiEvent(StrictMessage):
    type: Literal["ui.event"]
    protocol_version: Literal[1]
    event_id: int = Field(ge=1, le=9_007_199_254_740_991)
    event_type: Literal[
        "session.state",
        "source.status",
        "utterance.created",
        "utterance.updated",
        "utterance.finalized",
        "agent.queued",
        "agent.started",
        "agent.delta",
        "agent.completed",
        "agent.failed",
        "agent.cancelled",
        "settings.changed",
        "export.completed",
        "export.failed",
        "resync_required",
    ]
    aggregate_id: str | None = Field(default=None, max_length=256)
    created_at: datetime
    payload: dict[str, Any]


class ProtocolError(StrictMessage):
    type: Literal["protocol.error"]
    protocol_version: Literal[1]
    event_id: UUID | None = None
    code: Literal[
        "invalid_json",
        "invalid_message",
        "unsupported_protocol_version",
        "unauthorized",
        "hello_required",
        "unknown_message_type",
        "message_too_large",
        "rate_limited",
        "source_switch_rejected",
        "internal_error",
    ]
    message: str = Field(min_length=1, max_length=1024)
    recoverable: bool
    details: dict[str, Any] | None = None


ProtocolMessage = Annotated[
    ClientHello
    | SourceStatus
    | UtteranceUpsert
    | UtteranceFinalize
    | EventAck
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
