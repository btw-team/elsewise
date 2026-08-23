import threading
import time
from pathlib import Path

from elsewise.launcher.monitor import LifecycleActionRunner, RuntimeMonitor
from elsewise.runtime.controller import DaemonController, ServerStatus
from elsewise.settings.paths import AppPaths


def app_paths(root: Path) -> AppPaths:
    data = root / "data"
    runtime = data / "runtime"
    return AppPaths(
        data=data,
        config=root / "config",
        cache=root / "cache",
        runtime=runtime,
        database=data / "elsewise.sqlite3",
        exports=data / "exports",
        diagnostics=data / "diagnostics",
        agent_empty_cwd=runtime / "agent-empty-cwd",
    )


class StoppedController:
    def status(self) -> ServerStatus:
        return ServerStatus("stopped", url="http://127.0.0.1:38473")


def test_runtime_monitor_reports_lifecycle_without_tk_thread() -> None:
    received: list[dict[str, object]] = []
    ready = threading.Event()

    def callback(event: dict[str, object]) -> None:
        received.append(event)
        ready.set()

    monitor = RuntimeMonitor(StoppedController(), callback)  # type: ignore[arg-type]
    monitor.start()
    try:
        assert ready.wait(timeout=2)
    finally:
        monitor.stop()

    assert received[0]["kind"] == "lifecycle"
    assert received[0]["status"] == ServerStatus("stopped", url="http://127.0.0.1:38473")


def test_lifecycle_runner_converts_unexpected_error_to_status() -> None:
    received: list[ServerStatus] = []
    ready = threading.Event()

    def callback(status: ServerStatus) -> None:
        received.append(status)
        ready.set()

    def fail() -> ServerStatus:
        raise RuntimeError("failed safely")

    runner = LifecycleActionRunner(callback)
    assert runner.run(fail) is True
    assert ready.wait(timeout=2)
    assert received == [ServerStatus("error", message="failed safely")]


def test_runtime_monitor_consumes_refresh_before_websocket_reconnect() -> None:
    refresh_states: list[bool] = []

    class RunningController:
        @staticmethod
        def status() -> ServerStatus:
            return ServerStatus("running", url="http://127.0.0.1:38473")

    class RefreshMonitor(RuntimeMonitor):
        def _run_websocket(self, url: str) -> bool:
            _ = url
            refresh_states.append(self._refresh.is_set())
            if len(refresh_states) == 1:
                self.request_refresh()
            else:
                self._stop.set()
            return True

    monitor = RefreshMonitor(RunningController(), lambda _event: None)  # type: ignore[arg-type]

    monitor._run()

    assert refresh_states == [False, False]


def test_runtime_monitor_refresh_closes_active_websocket() -> None:
    class WebSocket:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    monitor = RuntimeMonitor(StoppedController(), lambda _event: None)  # type: ignore[arg-type]
    websocket = WebSocket()
    monitor._websocket = websocket  # type: ignore[assignment]

    monitor.request_refresh()

    assert websocket.closed is True
    assert monitor._refresh.is_set()


def test_runtime_monitor_refresh_after_real_restart_does_not_storm(
    tmp_path: Path,
    unused_tcp_port: int,
) -> None:
    controller = DaemonController(
        app_paths(tmp_path),
        port=unused_tcp_port,
        start_timeout=15,
        stop_timeout=15,
    )
    received: list[dict[str, object]] = []
    runtime_ready = threading.Event()

    def receive(event: dict[str, object]) -> None:
        received.append(event)
        if event.get("kind") == "runtime":
            runtime_ready.set()

    started = controller.start()
    assert started.state == "running"
    monitor = RuntimeMonitor(controller, receive)
    monitor.start()
    try:
        assert runtime_ready.wait(timeout=5)
        restarted = controller.restart()
        assert restarted.state == "running"
        assert restarted.pid != started.pid
        baseline = len(received)
        monitor.request_refresh()
        time.sleep(1.0)
        assert len(received) - baseline < 10
    finally:
        monitor.stop()
        if controller.status().state != "stopped":
            controller.force_stop()
