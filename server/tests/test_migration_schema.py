from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from elsewise.persistence.database import Database
from elsewise.persistence.models import Base
from elsewise.services.action_presets import ActionPresetService
from elsewise.services.builtin_actions import BUILTIN_ACTIONS, BUILTIN_PRESETS
from elsewise.services.buttons import ButtonService
from sqlalchemy import inspect

NEW_FACTORY_PRESETS = {
    "Language Practice": (
        "language_hint",
        "language_words",
        "language_start",
        "language_natural",
        "language_missed",
        "language_explain",
        "language_rescue",
    ),
    "Social Compass": (
        "social_read_room",
        "social_pushing",
        "social_landed",
        "social_softer",
        "social_space",
        "social_missing",
        "social_next",
    ),
    "Negotiation Coach": (
        "negotiation_interests",
        "negotiation_leverage",
        "negotiation_constraint",
        "negotiation_timing",
        "negotiation_counteroffer",
        "negotiation_conceding",
        "negotiation_status",
    ),
    "Interviewer": (
        "interviewer_follow_up",
        "interviewer_deeper",
        "interviewer_example",
        "interviewer_challenge",
        "interviewer_contradiction",
        "interviewer_missing",
        "interviewer_next",
    ),
}


def test_initial_migration_matches_models_and_seeds_factory_library(tmp_path: Path) -> None:
    database = Database.from_path(tmp_path / "migration.sqlite3")
    try:
        database.migrate()
        with database.engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"

        table_names = set(inspect(database.engine).get_table_names())
        assert set(Base.metadata.tables) == table_names - {"alembic_version"}
        assert "caption_events" not in table_names
        assert {
            "caption_event_tombstones",
            "caption_event_diagnostics",
            "caption_event_counters",
            "maintenance_state",
        }.issubset(table_names)

        actions = ButtonService(database).list_all()
        assert len(actions) == len(BUILTIN_ACTIONS) == 63
        action_ids = {record.key: record.id for record in actions}
        presets = ActionPresetService(database).list_all()
        assert len(presets) == len(BUILTIN_PRESETS) == 11
        assert [preset["name"] for preset in presets] == [
            definition["name"] for definition in BUILTIN_PRESETS
        ]
        assert presets[0]["is_default"] is True
        for preset, definition in zip(presets, BUILTIN_PRESETS, strict=True):
            assert preset["button_ids"] == [action_ids[key] for key in definition["action_keys"]]
    finally:
        database.dispose()

    assert differences == []


def test_new_factory_preset_definitions_are_complete_and_compact() -> None:
    action_keys = [definition["key"] for definition in BUILTIN_ACTIONS]
    assert len(action_keys) == len(set(action_keys))

    preset_names = [definition["name"] for definition in BUILTIN_PRESETS]
    assert preset_names[-4:] == list(NEW_FACTORY_PRESETS)

    preset_action_keys = {
        definition["name"]: definition["action_keys"] for definition in BUILTIN_PRESETS
    }
    assert {name: preset_action_keys[name] for name in NEW_FACTORY_PRESETS} == NEW_FACTORY_PRESETS

    known_action_keys = set(action_keys)
    assert all(
        set(definition["action_keys"]) <= known_action_keys for definition in BUILTIN_PRESETS
    )

    new_action_keys = {
        action_key for action_keys in NEW_FACTORY_PRESETS.values() for action_key in action_keys
    }
    new_actions = [
        definition for definition in BUILTIN_ACTIONS if definition["key"] in new_action_keys
    ]
    assert len(new_actions) == 28
    assert all(len(definition["label"]) <= 13 for definition in new_actions)


def test_initial_migration_can_downgrade_cleanly(tmp_path: Path) -> None:
    database_path = tmp_path / "downgrade.sqlite3"
    database = Database.from_path(database_path)
    database.migrate()
    database.dispose()
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "src" / "elsewise" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.downgrade(config, "base")

    database = Database.from_path(database_path)
    try:
        assert inspect(database.engine).get_table_names() == ["alembic_version"]
    finally:
        database.dispose()
