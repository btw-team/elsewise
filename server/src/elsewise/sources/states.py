from collections.abc import Mapping

from elsewise.services.errors import ServiceError

SOURCE_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "discovered": frozenset({"starting", "unavailable", "stopped"}),
    "starting": frozenset({"running", "stopping", "unavailable", "failed"}),
    "running": frozenset({"stopping", "unavailable", "failed"}),
    "stopping": frozenset({"stopped", "failed"}),
    "unavailable": frozenset({"starting", "running", "stopped"}),
    "failed": frozenset({"starting", "stopped"}),
    "stopped": frozenset(),
}


def require_source_transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in SOURCE_TRANSITIONS.get(current, frozenset()):
        raise ServiceError(
            "invalid_source_transition",
            f"Source cannot transition from {current} to {target}.",
            status_code=409,
        )
