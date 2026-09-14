from elsewise.audio.multiplexer import AudioFrameMultiplexer, AudioStreamHandle
from elsewise.audio.protocol import (
    AUDIO_HEADER_BYTES,
    AUDIO_PROTOCOL_VERSION,
    CONTROL_HEADER_BYTES,
    AudioFrame,
    AudioFrameFlags,
    AudioProtocolError,
    audio_payload_bytes_from_header,
    control_payload_bytes_from_header,
    decode_audio_frame,
    decode_control_frame,
    encode_audio_frame,
    encode_control_frame,
)

__all__ = [
    "AUDIO_PROTOCOL_VERSION",
    "AUDIO_HEADER_BYTES",
    "AudioFrame",
    "AudioFrameFlags",
    "AudioFrameMultiplexer",
    "AudioStreamHandle",
    "AudioProtocolError",
    "CONTROL_HEADER_BYTES",
    "decode_audio_frame",
    "decode_control_frame",
    "control_payload_bytes_from_header",
    "encode_audio_frame",
    "encode_control_frame",
    "audio_payload_bytes_from_header",
]
"""Native-audio contracts and runtime integration."""
