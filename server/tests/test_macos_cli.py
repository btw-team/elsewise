from pathlib import Path

from elsewise.launcher.macos_cli import MacCliManager, app_bundle_for


def make_bundle(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "Applications/Elsewise.app/Contents/MacOS/Elsewise"
    cli = executable.with_name("elsewise")
    executable.parent.mkdir(parents=True)
    executable.write_text("gui", encoding="utf-8")
    cli.write_text("cli", encoding="utf-8")
    return executable, cli


def test_mac_cli_installs_repairs_and_removes_owned_symlink(tmp_path: Path) -> None:
    executable, cli = make_bundle(tmp_path)
    destination = tmp_path / "bin/elsewise"
    destination.parent.mkdir()
    manager = MacCliManager(executable, destination)

    assert app_bundle_for(executable).name == "Elsewise.app"  # type: ignore[union-attr]
    assert manager.install().status == "installed"
    assert destination.is_symlink()
    assert destination.resolve() == cli.resolve()
    destination.unlink()
    destination.symlink_to(tmp_path / "Old/Elsewise.app/Contents/MacOS/elsewise")
    assert manager.install().status == "installed"
    assert destination.resolve() == cli.resolve()
    assert manager.remove().status == "removed"
    assert manager.remove().status == "not_installed"


def test_mac_cli_never_overwrites_unrelated_destination(tmp_path: Path) -> None:
    executable, _ = make_bundle(tmp_path)
    destination = tmp_path / "bin/elsewise"
    destination.parent.mkdir()
    destination.write_text("unrelated", encoding="utf-8")

    manager = MacCliManager(executable, destination)
    assert manager.install().status == "destination_conflict"
    assert manager.remove().status == "destination_conflict"
    assert destination.read_text(encoding="utf-8") == "unrelated"
