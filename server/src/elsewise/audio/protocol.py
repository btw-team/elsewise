import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntFlag
from types import MappingProxyType
from typing import Any
from uuid import UUID

AUDIO_PROTOCOL_VERSION = 1
CANONICAL_SAMPLE_RATE = 16_000
CANONICAL_CHANNELS = 1
CANONICAL_SAMPLE_FORMAT = "f32le"
MAX_CONTROL_MESSAGE_BYTES = 64 * 1024
MAX_AUDIO_FRAME_SAMPLES = 3_200
MAX_AUDIO_PAYLOAD_BYTES = MAX_AUDIO_FRAME_SAMPLES * 4

_CONTROL_LENGTH = struct.Struct("<I")
_AUDIO_HEADER = struct.Struct("<4sHH16s16sQQQII")
_AUDIO_MAGIC = b"EWA1"
CONTROL_HEADER_BYTES = _CONTROL_LENGTH.size
AUDIO_HEADER_BYTES = _AUDIO_HEADER.size


class AudioProtocolError(ValueError):
    pass


class AudioFrameFlags(IntFlag):
    NONE = 0
    DISCONTINUITY = 1 << 0
    XRUN = 1 << 1
    END_OF_STREAM = 1 << 2


@dataclass(frozen=True, slots=True)
class AudioFrame:
    source_id: UUID
    epoch_id: UUID
    sequence: int
    source_sample_position: int
    host_monotonic_ns: int
    frame_samples: int
    flags: AudioFrameFlags
    pcm: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.sequence < 2**64:
            raise AudioProtocolError("sequence is outside uint64")
        if not 0 <= self.source_sample_position < 2**64:
            raise AudioProtocolError("source_sample_position is outside uint64")
        if not 0 <= self.host_monotonic_ns < 2**64:
            raise AudioProtocolError("host_monotonic_ns is outside uint64")
        if not 0 <= self.frame_samples <= MAX_AUDIO_FRAME_SAMPLES:
            raise AudioProtocolError("frame_samples exceeds the protocol bound")
        if len(self.pcm) != self.frame_samples * 4:
            raise AudioProtocolError("PCM payload length does not match frame_samples")
        known_flags = (
            AudioFrameFlags.DISCONTINUITY | AudioFrameFlags.XRUN | AudioFrameFlags.END_OF_STREAM
        )
        if self.flags & ~known_flags:
            raise AudioProtocolError("audio frame contains unknown flags")


def encode_audio_frame(frame: AudioFrame) -> bytes:
    header = _AUDIO_HEADER.pack(
        _AUDIO_MAGIC,
        AUDIO_PROTOCOL_VERSION,
        int(frame.flags),
        frame.source_id.bytes,
        frame.epoch_id.bytes,
        frame.sequence,
        frame.source_sample_position,
        frame.host_monotonic_ns,
        frame.frame_samples,
        len(frame.pcm),
    )
    return header + frame.pcm


def decode_audio_frame(data: bytes) -> AudioFrame:
    if len(data) < _AUDIO_HEADER.size:
        raise AudioProtocolError("truncated audio frame header")
    (
        magic,
        version,
        raw_flags,
        source_id,
        epoch_id,
        sequence,
        source_sample_position,
        host_monotonic_ns,
        frame_samples,
        payload_bytes,
    ) = _AUDIO_HEADER.unpack_from(data)
    if magic != _AUDIO_MAGIC:
        raise AudioProtocolError("invalid audio frame magic")
    if version != AUDIO_PROTOCOL_VERSION:
        raise AudioProtocolError("unsupported audio protocol version")
    if frame_samples > MAX_AUDIO_FRAME_SAMPLES or payload_bytes > MAX_AUDIO_PAYLOAD_BYTES:
        raise AudioProtocolError("audio frame exceeds the protocol bound")
    if payload_bytes != frame_samples * 4:
        raise AudioProtocolError("PCM payload length does not match frame_samples")
    if len(data) != _AUDIO_HEADER.size + payload_bytes:
        raise AudioProtocolError("truncated or trailing audio frame payload")
    return AudioFrame(
        source_id=UUID(bytes=source_id),
        epoch_id=UUID(bytes=epoch_id),
        sequence=sequence,
        source_sample_position=source_sample_position,
        host_monotonic_ns=host_monotonic_ns,
        frame_samples=frame_samples,
        flags=AudioFrameFlags(raw_flags),
        pcm=data[_AUDIO_HEADER.size :],
    )


def audio_payload_bytes_from_header(header: bytes) -> int:
    if len(header) != AUDIO_HEADER_BYTES:
        raise AudioProtocolError("truncated audio frame header")
    magic, version, _, _, _, _, _, _, frame_samples, payload_bytes = _AUDIO_HEADER.unpack(header)
    if magic != _AUDIO_MAGIC or version != AUDIO_PROTOCOL_VERSION:
        raise AudioProtocolError("invalid audio frame header")
    if frame_samples > MAX_AUDIO_FRAME_SAMPLES or payload_bytes > MAX_AUDIO_PAYLOAD_BYTES:
        raise AudioProtocolError("audio frame exceeds the protocol bound")
    if payload_bytes != frame_samples * 4:
        raise AudioProtocolError("PCM payload length does not match frame_samples")
    return int(payload_bytes)


def encode_control_frame(message: Mapping[str, Any]) -> bytes:
    try:
        payload = json.dumps(
            dict(message),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AudioProtocolError("control message is not valid JSON") from exc
    if not payload or len(payload) > MAX_CONTROL_MESSAGE_BYTES:
        raise AudioProtocolError("control message exceeds the protocol bound")
    return _CONTROL_LENGTH.pack(len(payload)) + payload


def control_payload_bytes_from_header(header: bytes) -> int:
    if len(header) != CONTROL_HEADER_BYTES:
        raise AudioProtocolError("truncated control frame header")
    (payload_bytes,) = _CONTROL_LENGTH.unpack(header)
    if payload_bytes == 0 or payload_bytes > MAX_CONTROL_MESSAGE_BYTES:
        raise AudioProtocolError("control message exceeds the protocol bound")
    return int(payload_bytes)


def decode_control_frame(data: bytes) -> Mapping[str, Any]:
    if len(data) < _CONTROL_LENGTH.size:
        raise AudioProtocolError("truncated control frame header")
    (payload_bytes,) = _CONTROL_LENGTH.unpack_from(data)
    if payload_bytes == 0 or payload_bytes > MAX_CONTROL_MESSAGE_BYTES:
        raise AudioProtocolError("control message exceeds the protocol bound")
    if len(data) != _CONTROL_LENGTH.size + payload_bytes:
        raise AudioProtocolError("truncated or trailing control frame payload")
    try:
        message = json.loads(data[_CONTROL_LENGTH.size :])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AudioProtocolError("control message is not valid JSON") from exc
    if not isinstance(message, dict):
        raise AudioProtocolError("control message must be an object")
    if message.get("protocol_version") != AUDIO_PROTOCOL_VERSION:
        raise AudioProtocolError("unsupported audio protocol version")
    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type or len(message_type) > 64:
        raise AudioProtocolError("control message type is invalid")
    request_id = message.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise AudioProtocolError("control request_id is invalid")
    return MappingProxyType(message)
