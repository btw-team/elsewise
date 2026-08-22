from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from elsewise.agents.prompts import ContextStrategy, format_utterance
from elsewise.persistence.models import (
    AgentThreadRecord,
    CaptureSourceRecord,
    UtteranceRecord,
)
from elsewise.services.speaker_identity import classify_speaker, own_speaker_names
from elsewise.settings.config import GlobalSettings

CONTEXT_QUERY_CHUNK = 200


@dataclass(frozen=True, slots=True)
class ContextSelection:
    utterances: list[UtteranceRecord]
    speaker_roles: dict[str, str]
    truncated: bool = False


class AgentContextRepository:
    def __init__(self, db: Session, settings: GlobalSettings) -> None:
        self.db = db
        self.configured_names = own_speaker_names(settings)

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
                    UtteranceRecord.first_observed_at.desc(),
                    UtteranceRecord.first_client_seq.desc(),
                    UtteranceRecord.id.desc(),
                )
                .limit(1)
            )
            if latest is not None:
                statement = statement.where(
                    UtteranceRecord.last_observed_at
                    >= latest.last_observed_at - timedelta(minutes=value or 1)
                )
        elif strategy == "since_previous_turn" and thread.last_completed_boundary:
            boundary = self.db.get(UtteranceRecord, thread.last_completed_boundary)
            if boundary is not None:
                statement = statement.where(
                    UtteranceRecord.last_observed_at
                    >= boundary.last_observed_at - timedelta(minutes=value or 1)
                )

        descending = statement.order_by(
            UtteranceRecord.first_observed_at.desc(),
            UtteranceRecord.first_client_seq.desc(),
            UtteranceRecord.id.desc(),
        )
        selected_desc: list[UtteranceRecord] = []
        roles: dict[str, str] = {}
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
            source_ids = {utterance.source_id for utterance in chunk}
            platforms: dict[str, str] = {
                source_id: platform
                for source_id, platform in self.db.execute(
                    select(CaptureSourceRecord.source_id, CaptureSourceRecord.platform).where(
                        CaptureSourceRecord.source_id.in_(source_ids)
                    )
                ).all()
            }
            for utterance in chunk:
                role = classify_speaker(
                    utterance.speaker,
                    platforms.get(utterance.source_id),
                    self.configured_names,
                )
                roles[utterance.id] = role
                selected_desc.append(utterance)
                rendered_size += len(format_utterance(utterance, role)) + 1
                if rendered_size > hard_character_cap:
                    selected_desc.reverse()
                    return ContextSelection(selected_desc, roles, truncated=True)
            offset += len(chunk)
            if len(chunk) < chunk_size:
                break
        selected_desc.reverse()
        strategy_truncated = strategy == "last_utterances" and len(selected_desc) == hard_limit
        return ContextSelection(selected_desc, roles, truncated=strategy_truncated)
