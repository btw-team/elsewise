import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from elsewise.audio.helper_process import AudioHelperError, AudioHelperSupervisor
from elsewise.audio.multiplexer import AudioFrameMultiplexer
from elsewise.audio.protocol import AudioFrameFlags

SELF_SOURCE_ID = UUID("00000000-0000-4000-8000-000000000031")
SELF_EPOCH_ID = UUID("00000000-0000-4000-8000-000000000032")
REMOTE_SOURCE_ID = UUID("00000000-0000-4000-8000-000000000033")
REMOTE_EPOCH_ID = UUID("00000000-0000-4000-8000-000000000034")


def helper_executable() -> Path:
    return Path(__file__).parents[2] / "target" / "debug" / "elsewise-audio"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daemon_multiplexer_routes_two_lanes_from_one_helper() -> None:
    if os.name == "nt":
        pytest.skip("named-pipe IPC is part of the deferred release expansion")
    executable = helper_executable()
    if not executable.exists():
        pytest.skip("build the Rust helper with `cargo build --workspace`")
    helper = AudioHelperSupervisor(executable)
    multiplexer = AudioFrameMultiplexer(helper)
    self_stream = await multiplexer.start_synthetic(
        source_id=SELF_SOURCE_ID,
        epoch_id=SELF_EPOCH_ID,
        frame_count=3,
    )
    remote_stream = await multiplexer.start_synthetic(
        source_id=REMOTE_SOURCE_ID,
        epoch_id=REMOTE_EPOCH_ID,
        frame_count=2,
    )

    self_frames = [frame async for frame in self_stream.frames()]
    remote_frames = [frame async for frame in remote_stream.frames()]

    assert [frame.sequence for frame in self_frames] == [0, 1, 2]
    assert [frame.sequence for frame in remote_frames] == [0, 1]
    assert self_frames[-1].flags & AudioFrameFlags.END_OF_STREAM
    assert remote_frames[-1].flags & AudioFrameFlags.END_OF_STREAM
    assert helper.process_id is not None
    await multiplexer.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daemon_multiplexer_fails_lane_explicitly_on_queue_overflow() -> None:
    if os.name == "nt":
        pytest.skip("named-pipe IPC is part of the deferred release expansion")
    executable = helper_executable()
    if not executable.exists():
        pytest.skip("build the Rust helper with `cargo build --workspace`")
    multiplexer = AudioFrameMultiplexer(
        AudioHelperSupervisor(executable), maximum_queued_frames_per_stream=1
    )
    stream = await multiplexer.start_synthetic(
        source_id=SELF_SOURCE_ID,
        epoch_id=SELF_EPOCH_ID,
        frame_count=100,
    )

    await asyncio.sleep(0.05)
    with pytest.raises(AudioHelperError, match="overflowed"):
        _ = [frame async for frame in stream.frames()]
    await multiplexer.close()
