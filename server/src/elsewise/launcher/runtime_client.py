from collections.abc import Callable
from typing import Literal

from elsewise.launcher.monitor import MonitorEvent, RuntimeMonitor
from elsewise.runtime.controller import DaemonController, ServerStatus
from elsewise.settings.paths import AppPaths

LifecycleCommand = Literal["start", "stop", "restart", "force_stop"]


class RuntimeClient:
    """Toolkit-neutral command and event boundary for the local daemon."""

    def __init__(self, paths: AppPaths, callback: Callable[[MonitorEvent], None]) -> None:
        self._controller = DaemonController(paths)
        self._monitor = RuntimeMonitor(self._controller, callback)

    @property
    def url(self) -> str:
        return self._controller.url

    def start_monitoring(self) -> None:
        self._monitor.start()

    def stop_monitoring(self) -> None:
        self._monitor.stop()

    def request_refresh(self) -> None:
        self._monitor.request_refresh()

    def status(self) -> ServerStatus:
        return self._controller.status()

    def execute(self, command: LifecycleCommand) -> ServerStatus:
        if command == "start":
            return self._controller.start()
        if command == "stop":
            return self._controller.stop()
        if command == "restart":
            return self._controller.restart()
        return self._controller.force_stop()

    def start(self) -> ServerStatus:
        return self.execute("start")

    def stop(self) -> ServerStatus:
        return self.execute("stop")

    def restart(self) -> ServerStatus:
        return self.execute("restart")

    def force_stop(self) -> ServerStatus:
        return self.execute("force_stop")

    def open_web_gui(self) -> None:
        self._controller.open_web_gui()

    def pairing_action(self, action: str, target_id: str) -> bool:
        return self._controller.pairing_action(action, target_id)

    def set_agent_drain(self, enabled: bool) -> bool:
        return self._controller.set_agent_drain(enabled)

    def runtime_status_payload(self) -> dict[str, object] | None:
        return self._controller.runtime_status_payload()
