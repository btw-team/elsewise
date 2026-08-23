#!/usr/bin/env python3
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "packages"
FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def product_version() -> str:
    payload = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    return str(payload["version"])


def archive(browser: str, version: str) -> Path:
    source = ROOT / "extension" / "dist" / browser
    if not (source / "manifest.json").is_file():
        raise SystemExit(f"Missing {browser} extension build: {source}")
    target = OUTPUT / f"Elsewise-extension-{browser}-{version}.zip"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(item for item in source.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes(), compresslevel=9)
    return target


def main() -> None:
    version = product_version()
    for browser in ("chrome", "firefox"):
        print(archive(browser, version))


if __name__ == "__main__":
    main()
