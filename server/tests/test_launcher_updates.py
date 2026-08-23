import json
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Any

from elsewise.launcher.updates import UpdateChecker


class Response:
    def __init__(self, payload: dict[str, Any], *, etag: str = '"release-1"') -> None:
        self.payload = payload
        self.headers = {"ETag": etag}

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def stable_release(version: str, *, prerelease: bool = False) -> dict[str, Any]:
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/btw-team/elsewise/releases/tag/v{version}",
        "draft": False,
        "prerelease": prerelease,
    }


def test_update_checker_parses_stable_semver_and_uses_etag(tmp_path: Path) -> None:
    requests: list[Any] = []

    def open_release(request: Any, **_: object) -> Response:
        requests.append(request)
        return Response(stable_release("0.2.0"))

    checker = UpdateChecker(tmp_path / "update.json", "0.1.2", opener=open_release)
    first = checker.check(manual=True)
    checker.check(manual=True)

    assert first.status == "available"
    assert first.update_available is True
    assert first.latest_version == "0.2.0"
    assert requests[0].get_header("User-agent") == "Elsewise/0.1.2"
    assert requests[1].get_header("If-none-match") == '"release-1"'
    assert requests[0].full_url == UpdateChecker.API_URL


def test_automatic_checks_are_throttled_even_after_failure(tmp_path: Path) -> None:
    attempts = 0

    def offline(*_: object, **__: object) -> Response:
        nonlocal attempts
        attempts += 1
        raise TimeoutError

    now = datetime(2026, 8, 19, tzinfo=UTC)
    checker = UpdateChecker(tmp_path / "update.json", "0.1.2", opener=offline)
    assert checker.check(now=now).status == "offline"
    cached = checker.check(now=now + timedelta(hours=23))
    assert cached.status == "cached"
    assert cached.network_requested is False
    assert attempts == 1
    checker.check(now=now + timedelta(hours=25))
    assert attempts == 2


def test_update_checker_ignores_prerelease_and_handles_api_outcomes(tmp_path: Path) -> None:
    prerelease = UpdateChecker(
        tmp_path / "pre.json",
        "0.1.2",
        opener=lambda *_args, **_kwargs: Response(stable_release("0.2.0-rc.1", prerelease=True)),
    )
    assert prerelease.check(manual=True).status == "no_release"

    def missing(request: Any, **_: object) -> Response:
        raise urllib.error.HTTPError(request.full_url, 404, "not found", Message(), None)

    assert (
        UpdateChecker(tmp_path / "missing.json", "0.1.2", opener=missing).check(manual=True).status
        == "no_release"
    )
