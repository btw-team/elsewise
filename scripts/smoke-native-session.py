#!/usr/bin/env python3
"""Run a bounded, RAM-only native capture-to-ASR Session smoke."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from elsewise.audio.helper_process import AudioHelperSupervisor, resolve_audio_helper
from elsewise.audio.runtime import AudioRuntime
from elsewise.persistence.database import Database
from elsewise.persistence.models import SourceEpochRecord, UtteranceRecord
from elsewise.services.session_controller import SessionController
from elsewise.services.sessions import SessionService
from elsewise.services.transitions import TransitionExecutor
from elsewise.sources.manager import SourceManager
from elsewise.speech.session_runtime import NativeSessionRuntime
from elsewise.speech.worker_supervisor import SpeechWorkerSupervisor
from sqlalchemy import select


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--language", default="en")
    parser.add_argument("--remote-target", default=None)
    parser.add_argument("--helper", type=Path, default=None)
    parser.add_argument("--speech-worker", type=Path, default=None)
    args = parser.parse_args()
    if not 1.0 <= args.seconds <= 120.0:
        parser.error("--seconds must be between 1 and 120")
    return args


async def run(args: argparse.Namespace) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="elsewise-session-smoke-") as temporary:
        database = Database.from_path(Path(temporary) / "smoke.sqlite3")
        database.create_schema()
        sources = SourceManager(database)
        helper = (args.helper or resolve_audio_helper()).resolve()
        worker_command = (
            (str(args.speech_worker.resolve()),) if args.speech_worker is not None else None
        )
        audio = AudioRuntime(AudioHelperSupervisor(helper))
        runtime = NativeSessionRuntime(
            database,
            sources,
            audio,
            SpeechWorkerSupervisor(worker_command),
        )
        controller = SessionController(database, sources, TransitionExecutor(), runtime)
        session = SessionService(database).create(
            title="Native Session smoke",
            language=args.language,
            secondary_fallback_enabled=False,
            remote_target_key=args.remote_target,
        )
        try:
            await controller.start(session.id)
            deadline = asyncio.get_running_loop().time() + 30.0
            while asyncio.get_running_loop().time() < deadline:
                with database.transaction() as db:
                    states = list(
                        db.scalars(
                            select(SourceEpochRecord.state).where(
                                SourceEpochRecord.session_id == session.id
                            )
                        )
                    )
                if len(states) == 2 and all(state in {"running", "failed"} for state in states):
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(args.seconds)
            stopped = await controller.stop(session.id)
            with database.transaction() as db:
                epochs = list(
                    db.scalars(
                        select(SourceEpochRecord).where(SourceEpochRecord.session_id == session.id)
                    )
                )
                utterance_count = len(
                    list(
                        db.scalars(
                            select(UtteranceRecord.id).where(
                                UtteranceRecord.session_id == session.id
                            )
                        )
                    )
                )
            return {
                "status": "PASS"
                if stopped.recording_status == "stopped"
                and len(epochs) == 2
                and all(epoch.state == "stopped" for epoch in epochs)
                else "FAIL",
                "session_status": stopped.recording_status,
                "source_status": stopped.source_status,
                "utterance_count": utterance_count,
                "lanes": [
                    {
                        "state": epoch.state,
                        "backend": epoch.effective_backend,
                        "frames": epoch.received_event_count,
                        "drops": epoch.dropped_event_count,
                        "discontinuities": epoch.discontinuity_count,
                        "xruns": epoch.xrun_count,
                        "health": epoch.last_health_status,
                        "error_code": epoch.last_error_code,
                        "end_reason": epoch.end_reason,
                    }
                    for epoch in epochs
                ],
            }
        finally:
            await controller.close()
            await audio.close()
            database.dispose()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001 - CLI emits bounded smoke evidence.
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
