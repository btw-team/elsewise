from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy import update as sql_update

from elsewise.persistence.database import Database
from elsewise.persistence.models import (
    ActionPresetItemRecord,
    ActionPresetRecord,
    ButtonDefinitionRecord,
    SessionRecord,
)
from elsewise.services.errors import ServiceError
from elsewise.services.outbox import emit_ui_event

MAX_ACTION_PRESETS = 24
MAX_ACTIONS_PER_PRESET = 12


def preset_payload(record: ActionPresetRecord, button_ids: list[str]) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "is_default": record.is_default,
        "button_ids": button_ids,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


class ActionPresetService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_all(self) -> list[dict[str, Any]]:
        with self.database.transaction() as db:
            records = list(
                db.scalars(
                    select(ActionPresetRecord).order_by(
                        ActionPresetRecord.is_default.desc(),
                        ActionPresetRecord.created_at,
                    )
                )
            )
            memberships = list(
                db.execute(
                    select(
                        ActionPresetItemRecord.preset_id,
                        ActionPresetItemRecord.button_id,
                    ).order_by(
                        ActionPresetItemRecord.preset_id,
                        ActionPresetItemRecord.position,
                    )
                )
            )
        ids_by_preset: dict[str, list[str]] = {record.id: [] for record in records}
        for preset_id, button_id in memberships:
            ids_by_preset.setdefault(preset_id, []).append(button_id)
        return [preset_payload(record, ids_by_preset[record.id]) for record in records]

    def create(self, name: str, button_ids: list[str]) -> dict[str, Any]:
        with self.database.transaction() as db:
            preset_count = db.scalar(select(func.count(ActionPresetRecord.id))) or 0
            if preset_count >= MAX_ACTION_PRESETS:
                raise ServiceError(
                    "preset_limit_reached",
                    f"No more than {MAX_ACTION_PRESETS} action presets can be created.",
                )
            normalized_name = self._validate_name(db, name)
            validated_ids = self._validate_button_ids(db, button_ids)
            record = ActionPresetRecord(name=normalized_name)
            db.add(record)
            db.flush()
            self._replace_items(db, record.id, validated_ids)
            payload = preset_payload(record, validated_ids)
            emit_ui_event(db, "preset.created", record.id, payload)
            return payload

    def update(
        self, preset_id: str, *, name: str | None, button_ids: list[str] | None
    ) -> dict[str, Any]:
        with self.database.transaction() as db:
            record = db.get(ActionPresetRecord, preset_id)
            if record is None:
                raise ServiceError("preset_not_found", "Action preset not found.", status_code=404)
            if name is not None:
                if record.is_default and name.strip() != "Default":
                    raise ServiceError(
                        "default_preset_name_locked",
                        "The Default preset cannot be renamed.",
                    )
                record.name = self._validate_name(db, name, exclude_id=record.id)
            if button_ids is None:
                validated_ids = list(
                    db.scalars(
                        select(ActionPresetItemRecord.button_id)
                        .where(ActionPresetItemRecord.preset_id == record.id)
                        .order_by(ActionPresetItemRecord.position)
                    )
                )
            else:
                validated_ids = self._validate_button_ids(db, button_ids)
                self._replace_items(db, record.id, validated_ids)
            db.flush()
            payload = preset_payload(record, validated_ids)
            emit_ui_event(db, "preset.updated", record.id, payload)
            return payload

    def delete(self, preset_id: str) -> None:
        with self.database.transaction() as db:
            record = db.get(ActionPresetRecord, preset_id)
            if record is None:
                raise ServiceError("preset_not_found", "Action preset not found.", status_code=404)
            if record.is_default:
                raise ServiceError(
                    "default_preset_protected", "The Default preset cannot be deleted."
                )
            default_id = db.scalar(
                select(ActionPresetRecord.id).where(ActionPresetRecord.is_default.is_(True))
            )
            db.execute(
                sql_update(SessionRecord)
                .where(SessionRecord.action_preset_id == record.id)
                .values(action_preset_id=default_id)
            )
            db.delete(record)
            emit_ui_event(db, "preset.deleted", preset_id, {"id": preset_id, "deleted": True})

    @staticmethod
    def _replace_items(db: Any, preset_id: str, button_ids: list[str]) -> None:
        db.execute(
            delete(ActionPresetItemRecord).where(ActionPresetItemRecord.preset_id == preset_id)
        )
        for position, button_id in enumerate(button_ids):
            db.add(
                ActionPresetItemRecord(
                    preset_id=preset_id,
                    button_id=button_id,
                    position=position,
                )
            )

    @staticmethod
    def _validate_name(db: Any, name: str, *, exclude_id: str | None = None) -> str:
        normalized = name.strip()
        if not normalized:
            raise ServiceError(
                "preset_name_empty", "Preset name must not be blank.", status_code=422
            )
        statement = select(ActionPresetRecord.id).where(
            func.lower(ActionPresetRecord.name) == normalized.lower()
        )
        if exclude_id is not None:
            statement = statement.where(ActionPresetRecord.id != exclude_id)
        if db.scalar(statement):
            raise ServiceError("preset_name_exists", "An action preset with this name exists.")
        return normalized

    @staticmethod
    def _validate_button_ids(db: Any, button_ids: list[str]) -> list[str]:
        if len(button_ids) > MAX_ACTIONS_PER_PRESET:
            raise ServiceError(
                "preset_action_limit_reached",
                f"A preset can contain no more than {MAX_ACTIONS_PER_PRESET} actions.",
            )
        if len(set(button_ids)) != len(button_ids):
            raise ServiceError(
                "preset_action_duplicate", "An action can appear only once in a preset."
            )
        if not button_ids:
            return []
        existing_ids = set(
            db.scalars(
                select(ButtonDefinitionRecord.id).where(ButtonDefinitionRecord.id.in_(button_ids))
            )
        )
        if existing_ids != set(button_ids):
            raise ServiceError(
                "preset_action_not_found",
                "One or more actions do not exist.",
                status_code=404,
            )
        return list(button_ids)
