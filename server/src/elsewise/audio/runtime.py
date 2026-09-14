import asyncio
import platform
import time
from dataclasses import asdict
from typing import Any

from elsewise.audio.helper_process import AudioHelperError, AudioHelperSupervisor
from elsewise.audio.multiplexer import AudioFrameMultiplexer


class AudioRuntime:
    """Cached, privacy-safe view of the native helper runtime."""

    def __init__(self, helper: AudioHelperSupervisor, *, probe_ttl_seconds: float = 30.0) -> None:
        self.helper = helper
        self.streams = AudioFrameMultiplexer(helper)
        self.probe_ttl_seconds = probe_ttl_seconds
        self._lock = asyncio.Lock()
        self._probed_at = 0.0
        self._snapshot: dict[str, Any] | None = None

    async def snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not refresh
            and self._snapshot is not None
            and now - self._probed_at < self.probe_ttl_seconds
        ):
            return dict(self._snapshot)
        async with self._lock:
            now = time.monotonic()
            if (
                not refresh
                and self._snapshot is not None
                and now - self._probed_at < self.probe_ttl_seconds
            ):
                return dict(self._snapshot)
            try:
                descriptor = await self.helper.probe()
                snapshot: dict[str, Any] = {
                    "available": True,
                    "status": "ready",
                    "error_code": None,
                    "platform": platform.system().lower(),
                    "descriptor": asdict(descriptor),
                }
            except AudioHelperError as exc:
                message = str(exc)
                error_code = (
                    "helper_missing"
                    if "missing" in message
                    else (
                        "helper_version_mismatch"
                        if "version mismatch" in message
                        else "helper_unavailable"
                    )
                )
                snapshot = {
                    "available": False,
                    "status": "unavailable",
                    "error_code": error_code,
                    "platform": platform.system().lower(),
                    "descriptor": None,
                }
            self._snapshot = snapshot
            self._probed_at = now
            return dict(snapshot)

    async def source_inventory(self) -> tuple[dict[str, Any], ...]:
        """Return the helper's bounded, display-safe capture inventory."""
        await self.helper.start()
        sources = await self.helper.list_sources()
        return tuple(dict(source) for source in sources)

    async def close(self) -> None:
        await self.streams.close()
