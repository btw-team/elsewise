import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def protocol_root() -> Path:
    return Path(__file__).resolve().parents[4] / "protocol"


def schema_root() -> Path:
    packaged = Path(__file__).resolve().with_name("schema_files")
    if packaged.is_dir():
        return packaged
    return protocol_root() / "schemas"


@lru_cache
def schema_validator(message_type: str) -> Draft202012Validator:
    path = schema_root() / f"{message_type}.schema.json"
    schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_schema(message_type: str, payload: object) -> None:
    schema_validator(message_type).validate(payload)
