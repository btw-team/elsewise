from pathlib import Path
from uuid import UUID

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
    assert descriptor.capabilities == ("synthetic_audio",)

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
