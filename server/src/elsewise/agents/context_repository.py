from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from elsewise.agents.prompts import ContextStrategy, format_utterance
from elsewise.persistence.models import (
    AgentThreadRecord,
    UtteranceRecord,
    UtteranceSpeakerAssignmentRecord,
)
from elsewise.settings.config import GlobalSettings

CONTEXT_QUERY_CHUNK = 200


@dataclass(frozen=True, slots=True)
class ContextSelection:
    utterances: list[UtteranceRecord]
    speaker_roles: dict[str, str]
    speaker_labels: dict[str, str | None]
    truncated: bool = False


class AgentContextRepository:
    def __init__(self, db: Session, settings: GlobalSettings) -> None:
        self.db = db
        self.settings = settings

    def select(
        self,
        *,
        session_id: str,
        thread: AgentThreadRecord,
        strategy: ContextStrategy,
        value: int | None,
        hard_character_cap: int,
    ) -> ContextSelection:
        statement = select(UtteranceRecord).where(UtteranceRecord.session_id == session_id)
        hard_limit: int | None = None
        if strategy == "last_utterances":
            statement = statement.where(UtteranceRecord.final.is_(True))
            hard_limit = (value or 1) + 1
        elif strategy == "last_minutes":
            latest = self.db.scalar(
                select(UtteranceRecord)
                .where(UtteranceRecord.session_id == session_id)
                .order_by(
                    UtteranceRecord.first_session_offset_us.desc(),
                    UtteranceRecord.first_client_seq.desc(),
                    UtteranceRecord.id.desc(),
                )
                .limit(1)
            )
            if latest is not None:
                statement = statement.where(
                    UtteranceRecord.last_session_offset_us
                    >= latest.last_session_offset_us - (value or 1) * 60 * 1_000_000
                )
        elif strategy == "since_previous_turn" and thread.last_completed_boundary:
            boundary = self.db.get(UtteranceRecord, thread.last_completed_boundary)
            if boundary is not None:
                statement = statement.where(
                    UtteranceRecord.last_session_offset_us
                    >= boundary.last_session_offset_us - (value or 1) * 60 * 1_000_000
                )

        descending = statement.order_by(
            UtteranceRecord.first_session_offset_us.desc(),
            UtteranceRecord.first_client_seq.desc(),
            UtteranceRecord.id.desc(),
        )
        selected_desc: list[UtteranceRecord] = []
        roles: dict[str, str] = {}
        labels: dict[str, str | None] = {}
        rendered_size = 0
        offset = 0
        while True:
            remaining = hard_limit - len(selected_desc) if hard_limit is not None else None
            if remaining is not None and remaining <= 0:
                break
            chunk_size = (
                min(CONTEXT_QUERY_CHUNK, remaining)
                if remaining is not None
                else CONTEXT_QUERY_CHUNK
            )
            chunk = list(self.db.scalars(descending.offset(offset).limit(chunk_size)))
            if not chunk:
                break
            assignment_by_utterance = {
                assignment.utterance_id: assignment
                for assignment in self.db.scalars(
                    select(UtteranceSpeakerAssignmentRecord).where(
                        UtteranceSpeakerAssignmentRecord.utterance_id.in_(
                            {utterance.id for utterance in chunk}
                        )
                    )
                )
            }
            for utterance in chunk:
                assignment = assignment_by_utterance.get(utterance.id)
                role = assignment.speaker_role if assignment is not None else "unknown"
                roles[utterance.id] = role
                labels[utterance.id] = assignment.display_label if assignment else None
                selected_desc.append(utterance)
                rendered_size += len(format_utterance(utterance, role, labels[utterance.id])) + 1
                if rendered_size > hard_character_cap:
                    selected_desc.reverse()
                    return ContextSelection(selected_desc, roles, labels, truncated=True)
            offset += len(chunk)
            if len(chunk) < chunk_size:
                break
        selected_desc.reverse()
        strategy_truncated = strategy == "last_utterances" and len(selected_desc) == hard_limit
        return ContextSelection(selected_desc, roles, labels, truncated=strategy_truncated)
