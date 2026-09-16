from hashlib import sha256
from typing import Any

from elsewise.accessibility.contracts import AccessibilityNode


def _redact(value: str | None, *, show_text: bool) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())[:1_024]
    if show_text:
        return normalized
    digest = sha256(normalized.encode()).hexdigest()[:12]
    return f"<redacted:{digest}>"


def sanitized_node(node: AccessibilityNode, *, show_text: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": node.role[:128]}
    for key, value in (
        ("name", node.name),
        ("value", node.value),
        ("description", node.description),
    ):
        redacted = _redact(value, show_text=show_text)
        if redacted is not None:
            payload[key] = redacted
    if node.states:
        payload["states"] = list(node.states[:64])
    if node.children:
        payload["children"] = [
            sanitized_node(child, show_text=show_text) for child in node.children
        ]
    return payload
