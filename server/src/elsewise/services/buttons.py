from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from elsewise.persistence.database import Database
from elsewise.persistence.models import ButtonDefinitionRecord
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event

MAX_ACTIONS = 288


def button_payload(record: ButtonDefinitionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "key": record.key,
        "enabled": record.enabled,
        "label": record.label,
        "prompt_template": record.prompt_template,
        "context_strategy": record.context_strategy,
        "context_value": record.context_value,
        "hard_character_cap": record.hard_character_cap,
        "definition_version": record.definition_version,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


class ButtonService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_all(self) -> list[ButtonDefinitionRecord]:
        with self.database.transaction() as db:
            return list(
                db.scalars(
                    select(ButtonDefinitionRecord).order_by(ButtonDefinitionRecord.created_at)
                )
            )

    def create(self, values: dict[str, Any]) -> ButtonDefinitionRecord:
        with self.database.transaction() as db:
            action_count = db.scalar(select(func.count(ButtonDefinitionRecord.id))) or 0
            if action_count >= MAX_ACTIONS:
                raise ServiceError(
                    "action_limit_reached",
                    f"No more than {MAX_ACTIONS} actions can be created.",
                )
            values = dict(values)
            requested_key = values.pop("key", None)
            values["key"] = requested_key or f"action_{uuid4().hex}"
            if db.scalar(
                select(ButtonDefinitionRecord.id).where(ButtonDefinitionRecord.key == values["key"])
            ):
                raise ServiceError("button_key_exists", "Action key already exists.")
            record = ButtonDefinitionRecord(**values)
            db.add(record)
            db.flush()
            emit_ui_event(db, "button.created", record.id, button_payload(record))
            return record

    def update(self, button_id: str, changes: dict[str, Any]) -> ButtonDefinitionRecord:
        with self.database.transaction() as db:
            record = db.get(ButtonDefinitionRecord, button_id)
            if record is None:
                raise ServiceError("button_not_found", "Action button not found.", status_code=404)
            if "key" in changes and changes["key"] != record.key:
                duplicate = db.scalar(
                    select(ButtonDefinitionRecord.id).where(
                        ButtonDefinitionRecord.key == changes["key"]
                    )
                )
                if duplicate:
                    raise ServiceError("button_key_exists", "Action key already exists.")
            for key, value in changes.items():
                setattr(record, key, value)
            record.definition_version += 1
            db.flush()
            emit_ui_event(db, "button.updated", record.id, button_payload(record))
            return record

    def delete(self, button_id: str) -> None:
        with self.database.transaction() as db:
            record = db.get(ButtonDefinitionRecord, button_id)
            if record is None:
                raise ServiceError("button_not_found", "Action button not found.", status_code=404)
            db.delete(record)
            emit_ui_event(db, "button.deleted", button_id, {"id": button_id, "deleted": True})
