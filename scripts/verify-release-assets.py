#!/usr/bin/env python3
"""Validate a complete release bundle and produce deterministic SHA-256 sums."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def expected_names(version: str) -> set[str]:
    return {
        f"Elsewise-{version}-linux-x86_64.tar.gz",
        f"Elsewise-{version}-macOS-arm64.dmg",
        f"Elsewise-{version}-macOS-x86_64.dmg",
        f"Elsewise-{version}-windows-x64-setup.exe",
        f"Elsewise-{version}-x86_64.AppImage",
        f"Elsewise-extension-chrome-{version}.zip",
        f"Elsewise-extension-firefox-{version}.zip",
        f"elsewise-{version}-1.x86_64.rpm",
        f"elsewise-{version}-py3-none-any.whl",
        f"elsewise-{version}.tar.gz",
        f"elsewise_{version}_amd64.deb",
    }


def validate(directory: Path, version: str) -> list[Path]:
    expected = expected_names(version)
    actual = {
        path.name for path in directory.iterdir() if path.is_file() and path.name != "SHA256SUMS"
    }
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise ValueError("Invalid release asset inventory (" + "; ".join(details) + ")")
    return [directory / name for name in sorted(expected)]


def checksum_lines(paths: list[Path]) -> str:
    lines = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--write-checksums", action="store_true")
    arguments = parser.parse_args()

    paths = validate(arguments.directory, arguments.version)
    if arguments.write_checksums:
        (arguments.directory / "SHA256SUMS").write_text(checksum_lines(paths), encoding="utf-8")
    print(f"Verified {len(paths)} release assets for Elsewise {arguments.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
