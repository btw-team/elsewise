import asyncio
import contextlib
import time
from collections.abc import Mapping

from elsewise.agents.interface import AgentHealth, AgentModelOption, AgentProvider


class AgentProviderRegistry:
    def __init__(
        self,
        providers: Mapping[str, AgentProvider],
        *,
        shutdown_timeout: float = 15.0,
        health_retry_seconds: float = 30.0,
    ) -> None:
        self._providers = dict(providers)
        self._start_locks = {provider_id: asyncio.Lock() for provider_id in self._providers}
        self._last_start_attempt = {provider_id: 0.0 for provider_id in self._providers}
        self._replace_lock = asyncio.Lock()
        self.shutdown_timeout = shutdown_timeout
        self.health_retry_seconds = health_retry_seconds
        if not self._providers:
            raise ValueError("At least one agent provider is required.")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def get(self, provider_id: str) -> AgentProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ValueError(f"Unknown agent provider: {provider_id}") from exc

    async def health(self, provider_id: str, *, refresh: bool = False) -> AgentHealth:
        provider = self.get(provider_id)
        health = await provider.health()
        now = time.monotonic()
        retry_due = now - self._last_start_attempt[provider_id] >= self.health_retry_seconds
        if health.status == "stopped" or (
            refresh and retry_due and health.status not in {"ready", "starting"}
        ):
            async with self._start_locks[provider_id]:
                health = await provider.health()
                now = time.monotonic()
                retry_due = now - self._last_start_attempt[provider_id] >= self.health_retry_seconds
                if health.status == "stopped" or (
                    refresh and retry_due and health.status not in {"ready", "starting"}
                ):
                    self._last_start_attempt[provider_id] = now
                    with contextlib.suppress(Exception):
                        await provider.start()
                    health = await provider.health()
        return health

    async def health_all(self, *, refresh: bool = False) -> dict[str, AgentHealth]:
        results = await asyncio.gather(
            *(self.health(provider_id, refresh=refresh) for provider_id in self.ids)
        )
        return dict(zip(self._providers, results, strict=True))

    async def models(self, provider_id: str) -> tuple[AgentModelOption, ...]:
        provider = self.get(provider_id)
        health = await self.health(provider_id)
        if health.status != "ready":
            return ()
        return await provider.models()

    async def models_all(self) -> dict[str, tuple[AgentModelOption, ...]]:
        results = await asyncio.gather(*(self.models(provider_id) for provider_id in self.ids))
        return dict(zip(self._providers, results, strict=True))

    async def replace(self, provider_id: str, provider: AgentProvider) -> AgentProvider:
        async with self._replace_lock:
            previous = self.get(provider_id)
            await asyncio.wait_for(previous.stop(), timeout=self.shutdown_timeout)
            self._providers[provider_id] = provider
            self._start_locks[provider_id] = asyncio.Lock()
            self._last_start_attempt[provider_id] = 0.0
            return previous

    async def stop(self) -> None:
        results = await asyncio.gather(
            *(
                asyncio.wait_for(provider.stop(), timeout=self.shutdown_timeout)
                for provider in self._providers.values()
            ),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("Unable to stop all agent providers.", errors)
