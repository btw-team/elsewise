from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any, Literal

from elsewise.runtime.controller import ServerStatus

SourceRole = Literal["self", "remote", "secondary"]


@dataclass(frozen=True, slots=True)
class LaneViewState:
    role: SourceRole
    binding_state: str
    requested_mode: str
    effective_mode: str
    source_kind: str | None
    health_status: str
    connected: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class LauncherState:
    lifecycle: ServerStatus
    runtime_payload: dict[str, Any] = field(default_factory=dict)
    lanes: tuple[LaneViewState, ...] = ()
    pending_action: str = ""
    revision: int = 0


class LauncherStore:
    """Toolkit-neutral projection of daemon state for launcher views."""

    def __init__(
        self,
        initial_status: ServerStatus,
        *,
        metric_notification_interval_seconds: float = 0.1,
    ) -> None:
        self.state = LauncherState(lifecycle=initial_status)
        self.metric_notification_interval_seconds = metric_notification_interval_seconds
        self._last_metric_notification = 0.0

    def apply_lifecycle(self, status: ServerStatus) -> LauncherState:
        self.state = replace(
            self.state,
            lifecycle=status,
            revision=self.state.revision + 1,
        )
        return self.state

    def apply_runtime(self, payload: dict[str, Any], *, observed_at: float | None = None) -> bool:
        lanes = self._parse_lanes(payload.get("sources"))
        now = monotonic() if observed_at is None else observed_at
        metrics_only = self._state_without_metrics(payload) == self._state_without_metrics(
            self.state.runtime_payload
        )
        notify = (
            not metrics_only
            or now - self._last_metric_notification >= self.metric_notification_interval_seconds
        )
        if notify:
            self._last_metric_notification = now
        self.state = replace(
            self.state,
            runtime_payload=dict(payload),
            lanes=lanes,
            revision=self.state.revision + int(notify),
        )
        return notify

    def begin_action(self, name: str) -> None:
        self.state = replace(
            self.state,
            pending_action=name,
            revision=self.state.revision + 1,
        )

    def finish_action(self) -> str:
        action = self.state.pending_action
        self.state = replace(
            self.state,
            pending_action="",
            revision=self.state.revision + 1,
        )
        return action

    @staticmethod
    def _state_without_metrics(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key != "metrics"}

    @staticmethod
    def _parse_lanes(value: object) -> tuple[LaneViewState, ...]:
        if not isinstance(value, list):
            return ()
        lanes: list[LaneViewState] = []
        for item in value:
            if not isinstance(item, dict) or item.get("role") not in {
                "self",
                "remote",
                "secondary",
            }:
                continue
            role: SourceRole = item["role"]
            lanes.append(
                LaneViewState(
                    role=role,
                    binding_state=str(item.get("binding_state", "waiting")),
                    requested_mode=str(item.get("requested_mode", "auto")),
                    effective_mode=str(item.get("effective_mode", "unavailable")),
                    source_kind=(
                        str(item["source_kind"]) if item.get("source_kind") is not None else None
                    ),
                    health_status=str(item.get("health_status", "unavailable")),
                    connected=bool(item.get("connected", False)),
                    reason=str(item["reason"]) if item.get("reason") is not None else None,
                )
            )
        return tuple(sorted(lanes, key=lambda lane: lane.role))
