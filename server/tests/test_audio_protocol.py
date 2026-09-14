import struct
from uuid import UUID

import pytest
from elsewise.audio.protocol import (
    AUDIO_PROTOCOL_VERSION,
    CONTROL_HEADER_BYTES,
    MAX_AUDIO_FRAME_SAMPLES,
    AudioFrame,
    AudioFrameFlags,
    AudioProtocolError,
    control_payload_bytes_from_header,
    decode_audio_frame,
    decode_control_frame,
    encode_audio_frame,
    encode_control_frame,
)

SOURCE_ID = UUID("00000000-0000-4000-8000-000000000001")
EPOCH_ID = UUID("00000000-0000-4000-8000-000000000002")


def test_audio_frame_golden_vector_round_trip() -> None:
    pcm = struct.pack("<4f", 0.0, 0.25, -0.5, 1.0)
    frame = AudioFrame(
        source_id=SOURCE_ID,
        epoch_id=EPOCH_ID,
        sequence=7,
        source_sample_position=640,
        host_monotonic_ns=123_456_789,
        frame_samples=4,
        flags=AudioFrameFlags.DISCONTINUITY,
        pcm=pcm,
    )

    encoded = encode_audio_frame(frame)

    assert encoded.hex() == (
        "455741310100010000000000000040008000000000000001"
        "000000000000400080000000000000020700000000000000"
        "800200000000000015cd5b07000000000400000010000000"
        "000000000000803e000000bf0000803f"
    )
    assert decode_audio_frame(encoded) == frame


def test_audio_frame_rejects_malformed_or_oversized_input_before_payload_use() -> None:
    with pytest.raises(AudioProtocolError, match="truncated"):
        decode_audio_frame(b"EWA1")
    with pytest.raises(AudioProtocolError, match="bound"):
        AudioFrame(
            source_id=SOURCE_ID,
            epoch_id=EPOCH_ID,
            sequence=0,
            source_sample_position=0,
            host_monotonic_ns=0,
            frame_samples=MAX_AUDIO_FRAME_SAMPLES + 1,
            flags=AudioFrameFlags.NONE,
            pcm=b"",
        )


def test_control_frame_is_bounded_versioned_and_immutable() -> None:
    encoded = encode_control_frame(
        {
            "type": "helper.hello",
            "protocol_version": AUDIO_PROTOCOL_VERSION,
            "request_id": "request-1",
            "helper_instance_id": "helper-1",
        }
    )
    decoded = decode_control_frame(encoded)
    assert decoded["type"] == "helper.hello"
    with pytest.raises(TypeError):
        decoded["type"] = "changed"  # type: ignore[index]

    incompatible = encode_control_frame(
        {"type": "helper.hello", "protocol_version": AUDIO_PROTOCOL_VERSION + 1}
    )
    with pytest.raises(AudioProtocolError, match="version"):
        decode_control_frame(incompatible)


def test_control_header_rejects_oversized_payload_before_reading_it() -> None:
    assert CONTROL_HEADER_BYTES == 4
    oversized = struct.pack("<I", 64 * 1024 + 1)
    with pytest.raises(AudioProtocolError, match="bound"):
        control_payload_bytes_from_header(oversized)
