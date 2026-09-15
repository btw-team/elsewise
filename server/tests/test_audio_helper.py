import os
import signal
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from elsewise.audio.helper_process import AudioHelperError, AudioHelperSupervisor
from elsewise.audio.protocol import AudioFrameFlags

SOURCE_ID = UUID("00000000-0000-4000-8000-000000000001")
EPOCH_ID = UUID("00000000-0000-4000-8000-000000000002")


@pytest.mark.asyncio
async def test_missing_audio_helper_is_typed(tmp_path: Path) -> None:
    supervisor = AudioHelperSupervisor(tmp_path / "missing-helper")
    with pytest.raises(AudioHelperError, match="missing"):
        await supervisor.probe()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rust_helper_synthetic_stream_matches_python_protocol() -> None:
    executable = Path(__file__).parents[2] / "target" / "debug" / "elsewise-audio"
    if not executable.exists():
        pytest.skip("build the Rust helper with `cargo build --workspace`")
    supervisor = AudioHelperSupervisor(executable)
    descriptor = await supervisor.probe()
    assert descriptor.protocol_version == 1
    assert {
        "synthetic_audio",
        "multi_stream",
        "unix_socket_ipc",
    }.issubset(descriptor.capabilities)
    if sys.platform == "darwin":
        assert {
            "native_microphone",
            "native_process_audio",
            "native_system_audio",
        }.issubset(descriptor.capabilities)
    if sys.platform.startswith("linux"):
        assert {
            "native_microphone",
            "native_process_audio",
            "native_system_audio",
            "pipewire_capture",
            "pulseaudio_fallback",
        }.issubset(descriptor.capabilities)

    frames = [
        frame
        async for frame in supervisor.synthetic_frames(
            source_id=SOURCE_ID,
            epoch_id=EPOCH_ID,
            frame_count=3,
        )
    ]

    assert [frame.sequence for frame in frames] == [0, 1, 2]
    assert [frame.source_sample_position for frame in frames] == [0, 320, 640]
    assert all(frame.frame_samples == 320 for frame in frames)
    assert frames[-1].flags is AudioFrameFlags.END_OF_STREAM
    assert supervisor.running is False


@pytest.mark.asyncio
async def test_native_source_kind_is_validated_before_helper_start(tmp_path: Path) -> None:
    supervisor = AudioHelperSupervisor(tmp_path / "missing-helper")
    with pytest.raises(ValueError, match="source_kind"):
        await supervisor.start_native_source(
            source_kind="invalid_native_source",  # type: ignore[arg-type]
            source_id=SOURCE_ID,
            epoch_id=EPOCH_ID,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rust_helper_serves_two_streams_over_private_split_unix_sockets() -> None:
    if os.name == "nt":
        pytest.skip("named-pipe IPC is part of the deferred release expansion")
    executable = Path(__file__).parents[2] / "target" / "debug" / "elsewise-audio"
    if not executable.exists():
        pytest.skip("build the Rust helper with `cargo build --workspace`")
    supervisor = AudioHelperSupervisor(executable)
    second_source_id = uuid4()
    second_epoch_id = uuid4()
    await supervisor.start()
    assert supervisor.running is True
    assert supervisor.helper_instance_id is not None
    assert supervisor.clock_offset_ns is not None
    socket_directory = supervisor.socket_directory
    assert socket_directory is not None
    assert socket_directory.stat().st_mode & 0o777 == 0o700
    assert (socket_directory / "control.sock").stat().st_mode & 0o777 == 0o600
    assert (socket_directory / "data.sock").stat().st_mode & 0o777 == 0o600

    request_id = "idempotent-start"
    first_response = await supervisor.start_synthetic_source(
        source_id=SOURCE_ID,
        epoch_id=EPOCH_ID,
        frame_count=3,
        request_id=request_id,
    )
    repeated_response = await supervisor.start_synthetic_source(
        source_id=SOURCE_ID,
        epoch_id=EPOCH_ID,
        frame_count=3,
        request_id=request_id,
    )
    assert repeated_response == first_response
    await supervisor.start_synthetic_source(
        source_id=second_source_id,
        epoch_id=second_epoch_id,
        frame_count=2,
    )

    frames = [await supervisor.read_frame() for _ in range(5)]
    by_source = {
        source_id: [frame for frame in frames if frame.source_id == source_id]
        for source_id in (SOURCE_ID, second_source_id)
    }
    assert [frame.sequence for frame in by_source[SOURCE_ID]] == [0, 1, 2]
    assert [frame.sequence for frame in by_source[second_source_id]] == [0, 1]
    assert all(
        source_frames[-1].flags & AudioFrameFlags.END_OF_STREAM
        for source_frames in by_source.values()
    )
    health = await supervisor.health()
    assert health["active_streams"] == 0

    await supervisor.close()
    assert supervisor.running is False
    assert not socket_directory.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_control_plane_remains_responsive_when_data_consumer_is_slow() -> None:
    if os.name == "nt":
        pytest.skip("named-pipe IPC is part of the deferred release expansion")
    executable = Path(__file__).parents[2] / "target" / "debug" / "elsewise-audio"
    if not executable.exists():
        pytest.skip("build the Rust helper with `cargo build --workspace`")
    supervisor = AudioHelperSupervisor(executable)
    await supervisor.start_synthetic_source(
        source_id=SOURCE_ID,
        epoch_id=EPOCH_ID,
        frame_count=100_000,
    )

    sources = await supervisor.list_sources()
    assert sources[0]["source_kind"] == "synthetic_audio"
    source_health = await supervisor.source_health(SOURCE_ID)
    assert source_health["state"] == "running"
    health = await supervisor.health()
    assert health["status"] == "ready"
    assert health["data_queue_capacity_frames"] == 128
    stopped = await supervisor.stop_source(SOURCE_ID)
    assert stopped["was_running"] is True

    await supervisor.close()
    assert supervisor.running is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_supervisor_restarts_helper_after_a_crash() -> None:
    if os.name == "nt":
        pytest.skip("named-pipe IPC is part of the deferred release expansion")
    executable = Path(__file__).parents[2] / "target" / "debug" / "elsewise-audio"
    if not executable.exists():
        pytest.skip("build the Rust helper with `cargo build --workspace`")
    supervisor = AudioHelperSupervisor(executable)
    await supervisor.start()
    first_instance_id = supervisor.helper_instance_id
    process_id = supervisor.process_id
    assert process_id is not None
    os.kill(process_id, signal.SIGKILL)

    await supervisor.restart(maximum_attempts=2, initial_backoff_seconds=0.01)
    assert supervisor.running is True
    assert supervisor.helper_instance_id is not None
    assert supervisor.helper_instance_id != first_instance_id
    await supervisor.close()
