#!/usr/bin/env python3
"""Run a bounded, RAM-only native audio helper smoke and print JSON evidence."""

import argparse
import asyncio
import json
import struct
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from elsewise.audio.helper_process import AudioHelperSupervisor, resolve_audio_helper
from elsewise.audio.protocol import AudioFrame, AudioFrameFlags

SOURCE_KINDS = {
    "microphone": "native_microphone",
    "process": "native_process_audio",
    "system": "native_system_audio",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("list", *SOURCE_KINDS))
    parser.add_argument("--helper", type=Path, default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument("--frames", type=int, default=25)
    args = parser.parse_args()
    if not 1 <= args.frames <= 500:
        parser.error("--frames must be between 1 and 500")
    return args


async def capture(args: argparse.Namespace, helper: AudioHelperSupervisor) -> dict[str, Any]:
    source_kind = SOURCE_KINDS[args.source]
    target = args.target
    inventory = await helper.list_sources()
    if target is None and source_kind == "native_process_audio":
        target = next(
            (
                str(source["target_key"])
                for source in inventory
                if source.get("source_kind") == source_kind and source.get("active") is True
            ),
            None,
        )
        if target is None:
            raise RuntimeError("no active Core Audio process target is available")
    target = target or "default"
    source_id = uuid4()
    epoch_id = uuid4()
    frames: list[AudioFrame] = []
    await helper.start_native_source(
        source_kind=source_kind,  # type: ignore[arg-type]
        source_id=source_id,
        epoch_id=epoch_id,
        target_key=target,
    )
    try:
        for _ in range(args.frames):
            frames.append(await asyncio.wait_for(helper.read_frame(), timeout=5.0))
        health = dict(await helper.source_health(source_id))
    finally:
        await helper.stop_source(source_id)
    while not frames or not frames[-1].flags & AudioFrameFlags.END_OF_STREAM:
        frames.append(await asyncio.wait_for(helper.read_frame(), timeout=5.0))

    peak = 0.0
    for frame in frames:
        samples = struct.unpack(f"<{frame.frame_samples}f", frame.pcm)
        if samples:
            peak = max(peak, max(abs(sample) for sample in samples))
    return {
        "status": "PASS",
        "source_kind": source_kind,
        "target": target,
        "frames": len(frames),
        "sequences_contiguous": [frame.sequence for frame in frames] == list(range(len(frames))),
        "maximum_frame_samples": max(frame.frame_samples for frame in frames),
        "peak": peak,
        "end_of_stream": bool(frames[-1].flags & AudioFrameFlags.END_OF_STREAM),
        "health": health,
    }


async def run(args: argparse.Namespace) -> dict[str, Any] | list[dict[str, Any]]:
    executable = (args.helper or resolve_audio_helper()).resolve()
    helper = AudioHelperSupervisor(executable)
    try:
        await helper.start()
        if args.source == "list":
            return [dict(source) for source in await helper.list_sources()]
        return await capture(args, helper)
    finally:
        await helper.close()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001 - CLI converts failures to bounded evidence.
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
