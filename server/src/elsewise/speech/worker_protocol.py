import json
import struct
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, BinaryIO

SPEECH_WORKER_PROTOCOL_VERSION = 1
MAX_SPEECH_CONTROL_BYTES = 64 * 1024
SPEECH_CONTROL_HEADER_BYTES = 4
_LENGTH = struct.Struct("<I")


class SpeechWorkerProtocolError(ValueError):
    pass


def encode_worker_message(message: Mapping[str, Any]) -> bytes:
    outgoing = dict(message)
    if outgoing.get("protocol_version") != SPEECH_WORKER_PROTOCOL_VERSION:
        raise SpeechWorkerProtocolError("unsupported speech worker protocol version")
    try:
        payload = json.dumps(
            outgoing,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SpeechWorkerProtocolError("speech worker message is not valid JSON") from exc
    if not payload or len(payload) > MAX_SPEECH_CONTROL_BYTES:
        raise SpeechWorkerProtocolError("speech worker message exceeds the protocol bound")
    return _LENGTH.pack(len(payload)) + payload


def decode_worker_message(data: bytes) -> Mapping[str, Any]:
    if len(data) < SPEECH_CONTROL_HEADER_BYTES:
        raise SpeechWorkerProtocolError("truncated speech worker message header")
    payload_size = worker_payload_bytes_from_header(data[:SPEECH_CONTROL_HEADER_BYTES])
    if len(data) != SPEECH_CONTROL_HEADER_BYTES + payload_size:
        raise SpeechWorkerProtocolError("truncated or trailing speech worker message payload")
    try:
        value: Any = json.loads(data[SPEECH_CONTROL_HEADER_BYTES:])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpeechWorkerProtocolError("speech worker message is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SpeechWorkerProtocolError("speech worker message must be an object")
    if value.get("protocol_version") != SPEECH_WORKER_PROTOCOL_VERSION:
        raise SpeechWorkerProtocolError("unsupported speech worker protocol version")
    message_type = value.get("type")
    if not isinstance(message_type, str) or not message_type or len(message_type) > 128:
        raise SpeechWorkerProtocolError("speech worker message type is invalid")
    request_id = value.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise SpeechWorkerProtocolError("speech worker request_id is invalid")
    return MappingProxyType(value)


def worker_payload_bytes_from_header(header: bytes) -> int:
    if len(header) != SPEECH_CONTROL_HEADER_BYTES:
        raise SpeechWorkerProtocolError("truncated speech worker message header")
    (payload_size,) = _LENGTH.unpack(header)
    if payload_size == 0 or payload_size > MAX_SPEECH_CONTROL_BYTES:
        raise SpeechWorkerProtocolError("speech worker message exceeds the protocol bound")
    return int(payload_size)


def read_worker_message(stream: BinaryIO) -> Mapping[str, Any]:
    header = stream.read(SPEECH_CONTROL_HEADER_BYTES)
    if len(header) != SPEECH_CONTROL_HEADER_BYTES:
        raise SpeechWorkerProtocolError("truncated speech worker message header")
    payload_size = worker_payload_bytes_from_header(header)
    payload = stream.read(payload_size)
    if len(payload) != payload_size:
        raise SpeechWorkerProtocolError("truncated speech worker message payload")
    return decode_worker_message(header + payload)


def write_worker_message(stream: BinaryIO, message: Mapping[str, Any]) -> None:
    stream.write(encode_worker_message(message))
    stream.flush()
