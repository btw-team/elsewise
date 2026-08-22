from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from elsewise.launcher.updates import UpdateCache, UpdateCacheStore
from elsewise.settings.config import SettingsStore
from elsewise.settings.launcher import LauncherSettings, LauncherSettingsStore
from elsewise.settings.pairing import PairingManager


def test_global_settings_updates_are_atomic_within_process(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    changes = [
        {"ui_language": "fr"},
        {"default_meeting_language": "de"},
        {"default_agent_provider": "claude"},
        {"default_allow_workspace_write": True},
        {"default_allow_network": True},
        {"google_meet_own_name": "Meeting user"},
    ]
    barrier = Barrier(len(changes))

    def update(change: dict[str, object]) -> None:
        barrier.wait()
        # Launcher and server own separate SettingsStore instances, so the
        # regression test must exercise the shared on-disk lock rather than a
        # single instance's thread lock.
        SettingsStore(path).update(change)

    with ThreadPoolExecutor(max_workers=len(changes)) as executor:
        list(executor.map(update, changes))

    settings = store.load()
    assert settings.ui_language == "fr"
    assert settings.default_meeting_language == "de"
    assert settings.default_agent_provider == "claude"
    assert settings.default_allow_workspace_write is True
    assert settings.default_allow_network is True
    assert settings.google_meet_own_name == "Meeting user"


def test_pairing_regeneration_is_atomic_within_process(tmp_path: Path) -> None:
    manager = PairingManager(tmp_path / "pairing.json")
    workers = 12
    barrier = Barrier(workers)

    def regenerate(_: int) -> str:
        barrier.wait()
        return manager.regenerate()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        tokens = list(executor.map(regenerate, range(workers)))

    assert len(set(tokens)) == workers
    assert manager.metadata().generation == workers
    assert sum(manager.verify(token) for token in tokens) == 1
    assert (tmp_path / "pairing.json").stat().st_mode & 0o777 == 0o600


def test_pairing_ensure_recovers_corrupt_disposable_credentials(tmp_path: Path) -> None:
    path = tmp_path / "pairing.json"
    path.write_text("not json", encoding="utf-8")
    manager = PairingManager(path)

    metadata = manager.ensure()

    assert metadata.generation == 1
    assert "…" in metadata.masked_token
    assert path.stat().st_mode & 0o777 == 0o600


def test_pairing_ensure_creates_token_only_when_missing(tmp_path: Path) -> None:
    manager = PairingManager(tmp_path / "pairing.json")

    first = manager.ensure()
    token = manager.token()
    second = manager.ensure()

    assert len(token) >= 16
    assert first == second
    assert second.generation == 1


def test_pairing_manual_token_save_is_immediate_and_idempotent(tmp_path: Path) -> None:
    manager = PairingManager(tmp_path / "pairing.json")
    manager.ensure()
    manual = "manually-entered-pairing-token"

    updated = manager.save(f"  {manual}  ")
    unchanged = manager.save(manual)

    assert manager.token() == manual
    assert manager.verify(manual)
    assert updated.generation == 2
    assert unchanged == updated
    assert (tmp_path / "pairing.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("token", ["too-short", "x" * 4097])
def test_pairing_manual_token_rejects_invalid_length(tmp_path: Path, token: str) -> None:
    manager = PairingManager(tmp_path / "pairing.json")
    manager.ensure()

    with pytest.raises(ValueError, match="Pairing token"):
        manager.save(token)


@pytest.mark.parametrize("store_kind", ["settings", "launcher", "update_cache"])
def test_json_stores_recover_a_valid_backup(tmp_path: Path, store_kind: str) -> None:
    path = tmp_path / f"{store_kind}.json"
    store: Any
    expected: object
    if store_kind == "settings":
        store = SettingsStore(path)
        store.update({"ui_language": "fr"})
        store.update({"ui_language": "de"})
        expected = "fr"
    elif store_kind == "launcher":
        store = LauncherSettingsStore(path)
        store.save(LauncherSettings(stop_server_on_exit=False))
        store.save(LauncherSettings(stop_server_on_exit=True))
        expected = False
    else:
        store = UpdateCacheStore(path)
        store.save(UpdateCache(result="up_to_date"))
        store.save(UpdateCache(result="available", latest_version="9.0.0"))
        expected = "up_to_date"

    path.write_text("damaged primary", encoding="utf-8")

    recovered_store: Any
    actual: object
    if store_kind == "settings":
        recovered_store = SettingsStore(path)
        actual = recovered_store.load().ui_language
    elif store_kind == "launcher":
        recovered_store = LauncherSettingsStore(path)
        actual = recovered_store.load().stop_server_on_exit
    else:
        recovered_store = UpdateCacheStore(path)
        actual = recovered_store.load().result

    assert actual == expected
    assert recovered_store.recovery_notice is not None
    assert recovered_store.recovery_notice.source == "backup"
    assert "damaged primary" not in path.read_text(encoding="utf-8")


def test_settings_json_uses_defaults_when_primary_and_backup_are_invalid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    path.write_text("damaged again", encoding="utf-8")
    path.with_name("settings.json.bak").write_text("damaged backup", encoding="utf-8")
    defaults_store = SettingsStore(path)
    assert defaults_store.load().ui_language == "en"
    assert defaults_store.recovery_notice is not None
    assert defaults_store.recovery_notice.source == "defaults"
