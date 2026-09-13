import struct
from uuid import UUID

import pytest
from elsewise.audio.protocol import AudioFrame, AudioFrameFlags
from elsewise.speech.audio_buffer import AudioRegionUnavailable, RollingPcmBuffer
from elsewise.speech.vad import EndpointDetector, EndpointingConfig, EndpointKind, EnergyVad

SOURCE_ID = UUID("00000000-0000-4000-8000-000000000031")
EPOCH_ID = UUID("00000000-0000-4000-8000-000000000032")


def frame(
    sequence: int, amplitude: float, *, flags: AudioFrameFlags = AudioFrameFlags.NONE
) -> AudioFrame:
    return AudioFrame(
        source_id=SOURCE_ID,
        epoch_id=EPOCH_ID,
        sequence=sequence,
        source_sample_position=sequence * 4,
        host_monotonic_ns=sequence * 250_000,
        frame_samples=4,
        flags=flags,
        pcm=struct.pack("<4f", *([amplitude] * 4)),
    )


def test_rolling_pcm_buffer_is_byte_bounded_and_extracts_exact_regions() -> None:
    buffer = RollingPcmBuffer(maximum_seconds=60, maximum_bytes=32)
    buffer.append(frame(0, 0.1))
    buffer.append(frame(1, 0.2))
    buffer.append(frame(2, 0.3))

    assert buffer.size_bytes == 32
    assert buffer.frame_count == 2
    region = buffer.region(5, 11)
    assert struct.unpack("<6f", region.pcm) == pytest.approx((0.2, 0.2, 0.2, 0.3, 0.3, 0.3))
    with pytest.raises(AudioRegionUnavailable):
        buffer.region(0, 4)

    buffer.discard_before(8)
    assert buffer.frame_count == 1
    buffer.clear()
    assert buffer.size_bytes == 0


def test_endpoint_detector_emits_preroll_boundaries_and_discontinuity() -> None:
    detector = EndpointDetector(
        EnergyVad(rms_threshold=0.05),
        EndpointingConfig(
            start_frames=2,
            end_silence_frames=2,
            preroll_frames=3,
            maximum_phrase_frames=20,
        ),
    )
    assert detector.process(frame(0, 0.0)) == ()
    assert detector.process(frame(1, 0.1)) == ()
    started = detector.process(frame(2, 0.1))
    assert started[0].kind is EndpointKind.START
    assert [item.sequence for item in started[0].frames] == [0, 1, 2]

    assert detector.process(frame(3, 0.0))[0].kind is EndpointKind.AUDIO
    ended = detector.process(frame(4, 0.0))
    assert [item.kind for item in ended] == [EndpointKind.AUDIO, EndpointKind.END]
    assert ended[-1].reason == "silence"

    discontinuity = detector.process(frame(5, 0.1, flags=AudioFrameFlags.XRUN))
    assert discontinuity[-1].kind is EndpointKind.DISCONTINUITY
