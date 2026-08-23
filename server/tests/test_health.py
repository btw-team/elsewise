from pathlib import Path

import pytest
from elsewise.api.security import safe_extension_origin
from elsewise.main import app, create_app
from elsewise.persistence.database import Database
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_health_is_loopback_ready() -> None:
    response = TestClient(app, base_url="http://127.0.0.1:38473").get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.1.2"


@pytest.mark.parametrize(
    ("origin", "expected"),
    (
        ("chrome-extension://abcdefghijklmnopabcdefghijklmnop", True),
        ("moz-extension://12345678-1234-4abc-8def-1234567890ab", True),
        ("chrome-extension://not-an-extension", False),
        ("moz-extension://not-a-uuid", False),
        ("https://example.com", False),
        ("moz-extension://12345678-1234-4abc-8def-1234567890ab/path", False),
    ),
)
def test_extension_origins_are_limited_to_chromium_ids_and_firefox_uuids(
    origin: str, expected: bool
) -> None:
    assert safe_extension_origin(origin) is expected


def test_migration_failure_prevents_application_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_migration(_: Database) -> None:
        raise RuntimeError("migration failed intentionally")

    monkeypatch.setattr(Database, "migrate", fail_migration)
    application = create_app(database_url="sqlite://")
    with (
        pytest.raises(RuntimeError, match="migration failed intentionally"),
        TestClient(application, base_url="http://127.0.0.1:38473"),
    ):
        pass


def test_spa_fallback_does_not_hide_unknown_api_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_dist = tmp_path / "web"
    web_dist.mkdir()
    (web_dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    monkeypatch.setenv("ELSEWISE_WEB_DIST", str(web_dist))
    application = create_app(
        database_url="sqlite://",
        pairing_path=tmp_path / "pairing.json",
        settings_path=tmp_path / "settings.json",
    )

    with TestClient(application, base_url="http://127.0.0.1:38473") as client:
        api_response = client.get("/api/does-not-exist")
        page_response = client.get("/session/example")

    assert api_response.status_code == 404
    assert api_response.json() == {"error": {"code": "not_found", "message": "Not Found"}}
    assert page_response.status_code == 200
    assert '<div id="root"></div>' in page_response.text
