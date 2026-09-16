from elsewise.accessibility.backends import accessibility_backend
from elsewise.accessibility.contracts import AccessibilityNode
from elsewise.accessibility.explorer import sanitized_node


def test_accessibility_tree_is_redacted_by_default() -> None:
    node = AccessibilityNode(
        role="window",
        name="Private meeting",
        children=(AccessibilityNode(role="button", name="Alice"),),
    )

    redacted = sanitized_node(node)
    visible = sanitized_node(node, show_text=True)

    assert redacted["name"].startswith("<redacted:")
    assert redacted["children"][0]["name"].startswith("<redacted:")
    assert visible["name"] == "Private meeting"
    assert visible["children"][0]["name"] == "Alice"


def test_unsupported_accessibility_backend_has_actionable_health() -> None:
    backend = accessibility_backend("unsupported-os")
    health = backend.health()

    assert health.status == "unavailable"
    assert health.error_code == "unsupported_platform"
