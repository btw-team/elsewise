import os
import signal
import struct
import wave
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest
from elsewise.audio.protocol import AudioFrame, AudioFrameFlags
from elsewise.speech.backends.sherpa_worker import SherpaOnnxBackend
from elsewise.speech.contracts import SpeechEvent
from elsewise.speech.worker_protocol import (
    MAX_SPEECH_CONTROL_BYTES,
    SPEECH_WORKER_PROTOCOL_VERSION,
    SpeechWorkerProtocolError,
    decode_worker_message,
    encode_worker_message,
)
from elsewise.speech.worker_supervisor import SpeechWorkerError, SpeechWorkerSupervisor


def test_speech_worker_protocol_is_bounded_and_versioned() -> None:
    message = {
        "type": "worker.health",
        "protocol_version": SPEECH_WORKER_PROTOCOL_VERSION,
        "request_id": "health-1",
    }
    assert dict(decode_worker_message(encode_worker_message(message))) == message
    with pytest.raises(SpeechWorkerProtocolError, match="bound"):
        encode_worker_message(
            {
                **message,
                "padding": "x" * MAX_SPEECH_CONTROL_BYTES,
            }
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_speech_worker_lifecycle_and_missing_model_are_isolated(tmp_path: Path) -> None:
    worker = SpeechWorkerSupervisor()
    await worker.start()
    socket_directory = worker.socket_directory
    assert socket_directory is not None
    assert socket_directory.stat().st_mode & 0o777 == 0o700
    assert (socket_directory / "worker.sock").stat().st_mode & 0o777 == 0o600
    assert (await worker.health())["active_streams"] == 0

    with pytest.raises(SpeechWorkerError, match="model_missing"):
        await worker.create_stream(
            stream_id=str(uuid4()),
            profile="conservative",
            language="en",
            model_root=tmp_path / "missing-whisper",
            silero_model=tmp_path / "missing-silero.onnx",
            finalizer_root=None,
            threads=1,
        )
    assert (await worker.health())["status"] == "ready"

    await worker.close()
    assert not socket_directory.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_speech_worker_restarts_after_crash() -> None:
    worker = SpeechWorkerSupervisor()
    await worker.start()
    first_instance = worker.worker_instance_id
    process_id = worker.process_id
    assert process_id is not None
    os.kill(process_id, signal.SIGKILL)

    await worker.restart(maximum_attempts=2, initial_backoff_seconds=0.01)
    assert worker.worker_instance_id is not None
    assert worker.worker_instance_id != first_instance
    await worker.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_silero_whisper_worker_transcribes_fixture_when_enabled() -> None:
    if os.getenv("ELSEWISE_RUN_SPEECH_MODEL_SMOKE") != "1":
        pytest.skip("set ELSEWISE_RUN_SPEECH_MODEL_SMOKE=1 for the local model integration")
    inventory = Path(__file__).parents[2] / "models_loaded"
    whisper_root = inventory / "sherpa-onnx-whisper-base"
    silero_model = inventory / "silero/silero_vad.onnx"
    wav_path = whisper_root / "test_wavs/0.wav"
    if not all(path.is_file() for path in (silero_model, wav_path)):
        pytest.skip("local development model inventory is unavailable")

    worker = SpeechWorkerSupervisor()
    backend = SherpaOnnxBackend(
        worker,
        profile="conservative",
        model_root=whisper_root,
        silero_model=silero_model,
        threads=2,
    )
    stream = await backend.create_stream(language="en")
    try:
        events: list[SpeechEvent] = []
        for frame in wav_frames(wav_path):
            events.extend(await stream.push_audio(frame))
        events.extend(await stream.flush())
        assert events
        assert any(event.text.strip() for event in events)
        assert all(event.kind == "final" and event.durable for event in events)
    finally:
        with suppress(SpeechWorkerError):
            await stream.close()
        await worker.close()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["standard", "best"])
async def test_nemotron_profiles_transcribe_fixture_when_enabled(profile: str) -> None:
    if os.getenv("ELSEWISE_RUN_SPEECH_MODEL_SMOKE") != "1":
        pytest.skip("set ELSEWISE_RUN_SPEECH_MODEL_SMOKE=1 for the local model integration")
    inventory = Path(__file__).parents[2] / "models_loaded"
    nemotron_root = inventory / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11"
    parakeet_root = inventory / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    silero_model = inventory / "silero/silero_vad.onnx"
    wav_path = inventory / "sherpa-onnx-whisper-base/test_wavs/0.wav"
    required = [silero_model, wav_path, nemotron_root / "encoder.int8.onnx"]
    if profile == "best":
        required.append(parakeet_root / "encoder.int8.onnx")
    if not all(path.is_file() for path in required):
        pytest.skip("local development model inventory is unavailable")

    worker = SpeechWorkerSupervisor()
    backend = SherpaOnnxBackend(
        worker,
        profile=profile,  # type: ignore[arg-type]
        model_root=nemotron_root,
        silero_model=silero_model,
        finalizer_root=parakeet_root if profile == "best" else None,
        threads=2,
    )
    stream = await backend.create_stream(language="en")
    try:
        events: list[SpeechEvent] = []
        for frame in wav_frames(wav_path):
            events.extend(await stream.push_audio(frame))
        events.extend(await stream.flush())
        assert events
        assert any(event.text.strip() for event in events)
        assert events[-1].kind == "final"
        assert events[-1].durable is True
    finally:
        with suppress(SpeechWorkerError):
            await stream.close()
        await worker.close()


def wav_frames(path: Path) -> list[AudioFrame]:
    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getframerate() == 16_000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        pcm_i16 = wav_file.readframes(wav_file.getnframes())
    values = struct.unpack(f"<{len(pcm_i16) // 2}h", pcm_i16)
    source_id = uuid4()
    epoch_id = uuid4()
    frames = []
    for sequence, offset in enumerate(range(0, len(values), 320)):
        samples = [sample / 32_768 for sample in values[offset : offset + 320]]
        if len(samples) < 320:
            samples.extend([0.0] * (320 - len(samples)))
        frames.append(
            AudioFrame(
                source_id=source_id,
                epoch_id=epoch_id,
                sequence=sequence,
                source_sample_position=sequence * 320,
                host_monotonic_ns=sequence * 20_000_000,
                frame_samples=320,
                flags=AudioFrameFlags.NONE,
                pcm=struct.pack("<320f", *samples),
            )
        )
    return frames
