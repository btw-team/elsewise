import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_version_is_synchronized() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    expected = project["version"]
    for relative in ("package.json", "web/package.json", "extension/package.json"):
        payload = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert payload["version"] == expected

    with (ROOT / "uv.lock").open("rb") as handle:
        locked_packages = tomllib.load(handle)["package"]
    editable = next(
        package for package in locked_packages if package.get("source") == {"editable": "."}
    )
    assert editable["name"] == project["name"]
    assert editable["version"] == expected

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/version.py"), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
