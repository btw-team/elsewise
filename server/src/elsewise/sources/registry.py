from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from elsewise.sources.contracts import SourceCategory, SourceRole

Finalize = Callable[[str, float], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class SourceDriver:
    id: str
    version: str
    category: SourceCategory
    source_kinds: frozenset[str]
    supported_roles: frozenset[SourceRole]
    capabilities: frozenset[str]
    required_capabilities: frozenset[str] = frozenset()
    finalize: Finalize | None = None

    def __post_init__(self) -> None:
        if not self.source_kinds:
            raise ValueError("Source driver must support at least one source kind")
        if self.category is not SourceCategory.SEMANTIC and not self.supported_roles:
            raise ValueError("Capture source driver must support at least one source role")


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
    from elsewise.sources.drivers.browser_semantic import DRIVER as browser_semantic
    from elsewise.sources.drivers.native_audio import DRIVER as native_audio
    from elsewise.sources.drivers.synthetic import DRIVER as synthetic
    from elsewise.sources.drivers.synthetic_audio import DRIVER as synthetic_audio

    return SourceDriverRegistry((browser_semantic, synthetic, native_audio, synthetic_audio))
