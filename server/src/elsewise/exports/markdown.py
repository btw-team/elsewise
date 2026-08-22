import contextlib
import html
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from elsewise.observability import log_event
from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    AgentMessageRecord,
    AgentRunRecord,
    RecordingSegmentRecord,
    SessionRecord,
    UtteranceRecord,
)
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event


@dataclass(frozen=True, slots=True)
class ExportResult:
    directory: Path
    captions_path: Path
    agent_path: Path


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe(value: str) -> str:
    return html.escape(value, quote=False)


def _fenced(value: str) -> str:
    fence = "```"
    while fence in value:
        fence += "`"
    return f"{fence}text\n{value}\n{fence}"


def _session_directory(export_root: Path, session_id: str) -> Path:
    try:
        canonical_id = str(UUID(session_id))
    except ValueError as exc:
        raise ServiceError("invalid_session_id", "Session id is invalid.") from exc
    root = export_root.expanduser().resolve(strict=False)
    candidate = (root / canonical_id).resolve(strict=False)
    if candidate.parent != root:
        raise ServiceError("unsafe_export_path", "Unsafe export path.", status_code=500)
    return candidate


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def render_captions(
    session: SessionRecord,
    segments: list[RecordingSegmentRecord],
    utterances: list[UtteranceRecord],
) -> str:
    by_segment: dict[str, list[UtteranceRecord]] = {}
    for utterance in utterances:
        by_segment.setdefault(utterance.segment_id, []).append(utterance)
    lines = [
        f"# {_safe(session.title)} — captions",
        "",
        f"- Session: `{session.id}`",
        f"- Language: `{session.language}`",
        f"- Description: {_safe(session.description) if session.description else '—'}",
        f"- Started: `{_timestamp(session.started_at)}`",
        f"- Stopped: `{_timestamp(session.stopped_at)}`",
        "",
    ]
    for segment in segments:
        heading = "Recording started" if segment.sequence == 1 else "Recording resumed"
        lines.extend(
            [
                f"## {heading} · segment {segment.sequence}",
                "",
                f"`{_timestamp(segment.started_at)}` → `{_timestamp(segment.stopped_at)}`",
                "",
            ]
        )
        for utterance in by_segment.get(segment.id, []):
            if not utterance.final and session.recording_status != "running":
                continue
            partial = " [partial]" if not utterance.final else ""
            speaker = _safe(utterance.speaker or "Unknown speaker")
            text = _safe(utterance.text)
            lines.append(
                f"- `{_timestamp(utterance.last_observed_at)}` **{speaker}:** {text}{partial}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_agent(
    session: SessionRecord,
    runs: list[AgentRunRecord],
    messages: list[AgentMessageRecord],
) -> str:
    message_by_run = {message.run_id: message for message in messages}
    lines = [
        f"# {_safe(session.title)} — agent history",
        "",
        f"- Session: `{session.id}`",
        f"- Language: `{session.language}`",
        "",
    ]
    for run in runs:
        snapshot = run.button_snapshot
        label = str(snapshot.get("label") or "Initial prompt")
        lines.extend(
            [
                f"## {_safe(label)} · queue {run.queue_sequence}",
                "",
                f"- Created: `{_timestamp(run.created_at)}`",
                f"- Status: `{run.status}`",
                f"- Provider/model: `{run.provider}` / `{run.model or 'default'}`",
                f"- Transcript range: `{run.context_start or '—'}` → `{run.context_end or '—'}`",
                f"- Context strategy: `{run.context_strategy}`",
                f"- Cwd: `{_safe(run.cwd)}`",
                "",
                "### Actual prompt",
                "",
                _fenced(run.resolved_prompt),
                "",
            ]
        )
        message = message_by_run.get(run.id)
        if message is not None and message.text:
            lines.extend(["### Answer", "", _fenced(message.text), ""])
        if run.error_type or run.error_message:
            lines.extend(
                [
                    "### Error",
                    "",
                    f"`{run.error_type or 'error'}` — {_safe(run.error_message or '')}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


class ExportService:
    def __init__(self, database: Database, export_root: Path) -> None:
        self.database = database
        self.export_root = export_root

    def export(self, session_id: str) -> ExportResult:
        with self.database.transaction() as db:
            session = db.get(SessionRecord, session_id)
            if session is None:
                raise ServiceError("session_not_found", "Session not found.", status_code=404)
            if session.recording_status != "running":
                partials = list(
                    db.scalars(
                        select(UtteranceRecord).where(
                            UtteranceRecord.session_id == session_id,
                            UtteranceRecord.final.is_(False),
                        )
                    )
                )
                for utterance in partials:
                    utterance.final = True
                    emit_ui_event(
                        db,
                        "utterance.finalized",
                        utterance.id,
                        {
                            "session_id": session_id,
                            "utterance_id": utterance.utterance_id,
                            "revision": utterance.revision,
                            "speaker": utterance.speaker,
                            "text": utterance.text,
                            "final": True,
                            "reason": "export",
                        },
                    )
            segments = list(
                db.scalars(
                    select(RecordingSegmentRecord)
                    .where(RecordingSegmentRecord.session_id == session_id)
                    .order_by(RecordingSegmentRecord.sequence)
                )
            )
            utterances = list(
                db.scalars(
                    select(UtteranceRecord)
                    .where(UtteranceRecord.session_id == session_id)
                    .order_by(
                        UtteranceRecord.first_observed_at,
                        UtteranceRecord.first_client_seq,
                    )
                )
            )
            runs = list(
                db.scalars(
                    select(AgentRunRecord)
                    .where(AgentRunRecord.session_id == session_id)
                    .order_by(AgentRunRecord.queue_sequence)
                )
            )
            run_ids = [run.id for run in runs]
            messages = (
                list(
                    db.scalars(
                        select(AgentMessageRecord)
                        .where(AgentMessageRecord.run_id.in_(run_ids))
                        .order_by(AgentMessageRecord.sequence)
                    )
                )
                if run_ids
                else []
            )
            captions = render_captions(session, segments, utterances)
            agent = render_agent(session, runs, messages)

        directory = _session_directory(self.export_root, session_id)
        directory.mkdir(parents=True, exist_ok=True)
        captions_path = directory / "captions.md"
        agent_path = directory / "agent.md"
        _atomic_write(captions_path, captions)
        _atomic_write(agent_path, agent)
        with self.database.transaction() as db:
            emit_ui_event(
                db,
                "export.completed",
                session_id,
                {"session_id": session_id, "files": ["captions.md", "agent.md"]},
            )
        log_event(
            "export.completed",
            session_id=session_id,
            path=directory,
            file_count=2,
            result="success",
        )
        return ExportResult(directory, captions_path, agent_path)

    def cleanup(self, session_id: str) -> None:
        directory = _session_directory(self.export_root, session_id)
        if directory.is_dir():
            shutil.rmtree(directory)
            log_event(
                "export.cleaned",
                session_id=session_id,
                path=directory,
                result="success",
            )
