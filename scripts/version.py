#!/usr/bin/env python3
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = (ROOT / "package.json", ROOT / "web/package.json", ROOT / "extension/package.json")


def python_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def package_version(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def check() -> int:
    expected = python_version()
    mismatches = [path for path in PACKAGE_FILES if package_version(path) != expected]
    lock_path = ROOT / "package-lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if str(lock.get("version")) != expected:
            mismatches.append(lock_path)
    if mismatches:
        for path in mismatches:
            actual = (
                str(json.loads(path.read_text(encoding="utf-8")).get("version"))
                if path.suffix == ".json"
                else package_version(path)
            )
            print(
                f"{path.relative_to(ROOT)}: {actual} != {expected}",
                file=sys.stderr,
            )
        return 1
    print(expected)
    return 0


def set_version(value: str) -> int:
    try:
        parsed = Version(value)
    except InvalidVersion as exc:
        raise SystemExit(f"Invalid version: {value}") from exc
    if str(parsed) != value or parsed.is_prerelease or parsed.is_devrelease:
        raise SystemExit("Release version must be a normalized stable version")

    pyproject = ROOT / "pyproject.toml"
    source = pyproject.read_text(encoding="utf-8")
    source, count = re.subn(
        r'(?m)^(version = ")[^"]+("\s*)$', rf"\g<1>{value}\g<2>", source, count=1
    )
    if count != 1:
        raise SystemExit("Unable to locate project version in pyproject.toml")
    pyproject.write_text(source, encoding="utf-8")

    for path in PACKAGE_FILES:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = value
        path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n", encoding="utf-8")

    lock_path = ROOT / "package-lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["version"] = value
        packages = lock.get("packages", {})
        for key in ("", "extension", "web"):
            if isinstance(packages.get(key), dict):
                packages[key]["version"] = value
        lock_path.write_text(
            f"{json.dumps(lock, indent=2, ensure_ascii=False)}\n", encoding="utf-8"
        )
    return check()


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize the Elsewise product version")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--set", dest="new_version")
    operation.add_argument("--check", action="store_true", help="verify all version files")
    args = parser.parse_args()
    return set_version(args.new_version) if args.new_version else check()


if __name__ == "__main__":
    raise SystemExit(main())
