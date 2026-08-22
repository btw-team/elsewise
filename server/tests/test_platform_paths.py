from pathlib import Path

import platformdirs.windows
import pytest
from platformdirs.macos import MacOS
from platformdirs.unix import Unix
from platformdirs.windows import Windows


@pytest.mark.parametrize(
    ("dirs_type", "expected_fragment"),
    [
        (Unix, ".local/share/Elsewise"),
        (MacOS, "Library/Application Support/Elsewise"),
        (Windows, "Elsewise"),
    ],
)
def test_platformdirs_never_resolves_to_repository(
    dirs_type: type[Unix] | type[MacOS] | type[Windows],
    expected_fragment: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/tmp/elsewise-test-home")
    monkeypatch.setenv("LOCALAPPDATA", "/tmp/elsewise-test-local-app-data")
    monkeypatch.setenv("APPDATA", "/tmp/elsewise-test-roaming-app-data")
    if dirs_type is Windows:
        monkeypatch.setattr(
            platformdirs.windows,
            "get_win_folder",
            lambda _name: "/tmp/elsewise-test-local-app-data",
        )
    dirs = dirs_type("Elsewise", appauthor=False)
    resolved = str(dirs.user_data_path).replace("\\", "/")

    assert expected_fragment in resolved
    assert Path.cwd().as_posix() not in resolved
