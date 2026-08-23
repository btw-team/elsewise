import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import certifi
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

from elsewise.settings.json_store import RecoverableJsonFile, RecoveryNotice


class HttpResponse(Protocol):
    headers: Any

    def read(self) -> bytes: ...

    def __enter__(self) -> "HttpResponse": ...

    def __exit__(self, *args: object) -> None: ...


UpdateStatus = Literal[
    "not_checked",
    "cached",
    "up_to_date",
    "available",
    "no_release",
    "offline",
    "rate_limited",
    "error",
]


class UpdateCache(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_attempt: datetime | None = None
    last_success: datetime | None = None
    etag: str | None = None
    latest_version: str | None = None
    release_url: str | None = None
    result: UpdateStatus = "not_checked"


class UpdateResult(BaseModel):
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    last_success: datetime | None = None
    status: UpdateStatus
    update_available: bool = False
    network_requested: bool = False


class UpdateCacheStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.recovery_notice: RecoveryNotice | None = None

    def load(self) -> UpdateCache:
        file = self._file()
        result = file.load()
        self.recovery_notice = file.recovery_notice or self.recovery_notice
        return result

    def save(self, cache: UpdateCache) -> None:
        self._file().save(cache)

    def _file(self) -> RecoverableJsonFile[UpdateCache]:
        return RecoverableJsonFile(
            self.path,
            parse=UpdateCache.model_validate_json,
            serialize=lambda value: value.model_dump_json(indent=2),
            default=UpdateCache,
        )


class UpdateChecker:
    API_URL = "https://api.github.com/repos/btw-team/elsewise/releases/latest"
    AUTOMATIC_INTERVAL = timedelta(hours=24)

    def __init__(
        self,
        cache_path: Path,
        current_version: str,
        *,
        opener: Callable[..., HttpResponse] = urllib.request.urlopen,
        timeout: float = 4.0,
    ) -> None:
        self.store = UpdateCacheStore(cache_path)
        self.current_version = current_version
        self.opener = opener
        self.timeout = timeout

    def cached_result(self) -> UpdateResult:
        return self._result(self.store.load(), status="cached")

    def check(self, *, manual: bool = False, now: datetime | None = None) -> UpdateResult:
        checked_at = now or datetime.now(UTC)
        cache = self.store.load()
        if (
            not manual
            and cache.last_attempt is not None
            and checked_at - cache.last_attempt < self.AUTOMATIC_INTERVAL
        ):
            return self._result(cache, status="cached")

        cache.last_attempt = checked_at
        self.store.save(cache)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"Elsewise/{self.current_version}",
        }
        if cache.etag:
            headers["If-None-Match"] = cache.etag
        request = urllib.request.Request(self.API_URL, headers=headers)
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with self.opener(request, timeout=self.timeout, context=context) as response:
                payload = cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
                return self._accept_payload(cache, payload, response.headers, checked_at)
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                cache.last_success = checked_at
                self.store.save(cache)
                return self._result(cache, status=cache.result, network_requested=True)
            if exc.code == 404:
                cache.result = "no_release"
                cache.latest_version = None
                cache.release_url = None
                cache.last_success = checked_at
                self.store.save(cache)
                return self._result(cache, network_requested=True)
            status: UpdateStatus = "rate_limited" if exc.code in {403, 429} else "error"
            return self._result(cache, status=status, network_requested=True)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return self._result(cache, status="offline", network_requested=True)

    def _accept_payload(
        self,
        cache: UpdateCache,
        payload: dict[str, Any],
        headers: Any,
        checked_at: datetime,
    ) -> UpdateResult:
        if payload.get("draft") or payload.get("prerelease"):
            cache.result = "no_release"
            cache.latest_version = None
            cache.release_url = None
        else:
            tag = str(payload.get("tag_name", "")).removeprefix("v")
            release_url = str(payload.get("html_url", ""))
            try:
                latest = Version(tag)
                current = Version(self.current_version)
            except InvalidVersion:
                cache.result = "error"
            else:
                if latest.is_prerelease or latest.is_devrelease or not release_url:
                    cache.result = "no_release"
                    cache.latest_version = None
                    cache.release_url = None
                else:
                    cache.latest_version = str(latest)
                    cache.release_url = release_url
                    cache.result = "available" if latest > current else "up_to_date"
        cache.etag = headers.get("ETag") if headers is not None else None
        cache.last_success = checked_at
        self.store.save(cache)
        return self._result(cache, network_requested=True)

    def _result(
        self,
        cache: UpdateCache,
        *,
        status: UpdateStatus | None = None,
        network_requested: bool = False,
    ) -> UpdateResult:
        resolved_status = status or cache.result
        return UpdateResult(
            current_version=self.current_version,
            latest_version=cache.latest_version,
            release_url=cache.release_url,
            last_success=cache.last_success,
            status=resolved_status,
            update_available=cache.result == "available",
            network_requested=network_requested,
        )
