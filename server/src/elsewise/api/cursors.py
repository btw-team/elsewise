import base64
import json
from datetime import datetime
from typing import Any

from elsewise.services.errors import ServiceError


def encode_cursor(values: dict[str, Any]) -> str:
    payload = json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceError(
            "invalid_cursor", "The pagination cursor is invalid.", status_code=422
        ) from exc
    if not isinstance(payload, dict):
        raise ServiceError("invalid_cursor", "The pagination cursor is invalid.", status_code=422)
    return payload


def utterance_cursor(observed_at: datetime, client_seq: int, record_id: str) -> str:
    return encode_cursor({"at": observed_at.isoformat(), "seq": client_seq, "id": record_id})


def parse_utterance_cursor(value: str | None) -> tuple[datetime, int, str] | None:
    payload = decode_cursor(value)
    if payload is None:
        return None
    try:
        return datetime.fromisoformat(str(payload["at"])), int(payload["seq"]), str(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceError(
            "invalid_cursor", "The pagination cursor is invalid.", status_code=422
        ) from exc


def agent_cursor(queue_sequence: int, record_id: str) -> str:
    return encode_cursor({"seq": queue_sequence, "id": record_id})


def parse_agent_cursor(value: str | None) -> tuple[int, str] | None:
    payload = decode_cursor(value)
    if payload is None:
        return None
    try:
        return int(payload["seq"]), str(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceError(
            "invalid_cursor", "The pagination cursor is invalid.", status_code=422
        ) from exc
