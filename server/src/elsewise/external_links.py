import json
from pathlib import Path
from typing import TypedDict, cast


class ExternalLinks(TypedDict):
    project: str
    releases: str
    documentation: str
    chrome_store: str
    firefox_store: str
    support: str
    license: str


def manifest_path() -> Path:
    packaged = Path(__file__).resolve().parent / "assets" / "external-links.json"
    repository = Path(__file__).resolve().parents[3] / "shared" / "external-links.json"
    return packaged if packaged.is_file() else repository


def load_external_links() -> ExternalLinks:
    value = json.loads(manifest_path().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("External link manifest must be an object")
    required = set(ExternalLinks.__required_keys__)
    if set(value) != required or any(not isinstance(value[key], str) for key in required):
        raise ValueError("External link manifest has an invalid shape")
    return cast(ExternalLinks, value)
