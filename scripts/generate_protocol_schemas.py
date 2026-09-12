"""Generate per-message JSON Schemas from the authoritative Pydantic models."""

import json
from pathlib import Path

from elsewise.protocol.models import (
    CaptionFinalize,
    CaptionUpsert,
    ClientHello,
    EventAck,
    Heartbeat,
    HeartbeatAck,
    PairingApproved,
    PairingCancel,
    PairingCancelled,
    PairingDenied,
    PairingError,
    PairingExpired,
    PairingPending,
    PairingRequest,
    ProtocolError,
    ServerHello,
    SourceCommandAck,
    SourceDiscovered,
    SourceHealth,
    SourceStart,
    SourceStop,
    UiEvent,
)

ROOT = Path(__file__).resolve().parents[1] / "protocol" / "schemas"
SCHEMAS = {
    "pairing.request": PairingRequest,
    "pairing.cancel": PairingCancel,
    "pairing.pending": PairingPending,
    "pairing.approved": PairingApproved,
    "pairing.denied": PairingDenied,
    "pairing.expired": PairingExpired,
    "pairing.cancelled": PairingCancelled,
    "pairing.error": PairingError,
    "client.hello": ClientHello,
    "server.hello": ServerHello,
    "heartbeat": Heartbeat,
    "heartbeat.ack": HeartbeatAck,
    "source.discovered": SourceDiscovered,
    "source.health": SourceHealth,
    "source.start": SourceStart,
    "source.stop": SourceStop,
    "source.command_ack": SourceCommandAck,
    "caption.upsert": CaptionUpsert,
    "caption.finalize": CaptionFinalize,
    "event.ack": EventAck,
    "ui.event": UiEvent,
    "protocol.error": ProtocolError,
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for path in ROOT.glob("*.schema.json"):
        path.unlink()
    for message_type, model in SCHEMAS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$id"] = f"https://elsewise.local/protocol/v2/{message_type}.schema.json"
        path = ROOT / f"{message_type}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
