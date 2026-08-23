import ast
import json
from pathlib import Path
from typing import Any, TypedDict

import pytest
from elsewise.protocol.models import parse_protocol_message
from elsewise.protocol.schemas import protocol_root, schema_root, validate_schema
from elsewise.settings.limits import MAX_CAPTION_TEXT_LENGTH
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError


class FixtureCase(TypedDict):
    file: str
    schema: str
    valid: bool


def fixture_cases() -> list[FixtureCase]:
    manifest: dict[str, list[FixtureCase]] = json.loads(
        (protocol_root() / "fixtures" / "manifest.json").read_text(encoding="utf-8")
    )
    return manifest["cases"]


@pytest.mark.parametrize("case", fixture_cases(), ids=lambda case: case["file"])
def test_schema_and_pydantic_fixture_parity(case: FixtureCase) -> None:
    payload: dict[str, Any] = json.loads(
        (protocol_root() / "fixtures" / case["file"]).read_text(encoding="utf-8")
    )

    if case["valid"]:
        validate_schema(case["schema"], payload)
        message = parse_protocol_message(payload)
        assert message.type == payload["type"]
    else:
        with pytest.raises((JsonSchemaValidationError, PydanticValidationError, FileNotFoundError)):
            parse_protocol_message(payload)


def test_caption_text_hard_limit() -> None:
    fixture = protocol_root() / "fixtures" / "valid" / "utterance.upsert.json"
    payload: dict[str, Any] = json.loads(fixture.read_text(encoding="utf-8"))
    payload["text"] = "x" * (MAX_CAPTION_TEXT_LENGTH + 1)
    with pytest.raises(JsonSchemaValidationError):
        parse_protocol_message(payload)


def test_protocol_root_is_repository_protocol_directory() -> None:
    assert protocol_root() == Path(__file__).resolve().parents[2] / "protocol"
    assert schema_root() == protocol_root() / "schemas"


def test_every_rest_error_code_is_registered_in_the_shared_catalog() -> None:
    root = Path(__file__).resolve().parents[2]
    discovered: set[str] = {"not_found", "request_failed"}
    for path in (root / "server" / "src" / "elsewise").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "ServiceError"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    discovered.add(node.args[0].value)
                if isinstance(node.func, ast.Name) and node.func.id == "HTTPException":
                    for keyword in node.keywords:
                        if (
                            keyword.arg == "detail"
                            and isinstance(keyword.value, ast.Constant)
                            and isinstance(keyword.value.value, str)
                            and keyword.value.value.isidentifier()
                        ):
                            discovered.add(keyword.value.value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "code"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        discovered.add(value.value)

    catalog = json.loads((root / "shared" / "api-errors.json").read_text(encoding="utf-8"))
    registered = {entry["code"] for entry in catalog}
    assert len(registered) == len(catalog)
    assert discovered == registered
    documentation = (root / "docs" / "development" / "api-errors.md").read_text(encoding="utf-8")
    assert all(f"`{code}`" in documentation for code in registered)
