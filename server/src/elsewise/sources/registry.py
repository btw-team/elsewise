from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

Finalize = Callable[[str, float], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class SourceDriver:
    id: str
    version: str
    capabilities: frozenset[str]
    required_capabilities: frozenset[str] = frozenset()
    finalize: Finalize | None = None


class SourceDriverRegistry:
    def __init__(self, drivers: Iterable[SourceDriver] = ()) -> None:
        self._drivers = {driver.id: driver for driver in drivers}

    def register(self, driver: SourceDriver) -> None:
        if driver.id in self._drivers:
            raise ValueError(f"Source driver already registered: {driver.id}")
        self._drivers[driver.id] = driver

    def require(self, driver_id: str) -> SourceDriver:
        try:
            return self._drivers[driver_id]
        except KeyError as exc:
            from elsewise.services.errors import ServiceError

            raise ServiceError(
                "unsupported_source_driver",
                f"Unknown source driver: {driver_id}",
                status_code=422,
            ) from exc

    def all(self) -> tuple[SourceDriver, ...]:
        return tuple(self._drivers.values())


def default_source_registry() -> SourceDriverRegistry:
    from elsewise.sources.drivers.browser_captions import DRIVER as browser_captions
    from elsewise.sources.drivers.synthetic import DRIVER as synthetic

    return SourceDriverRegistry((browser_captions, synthetic))
