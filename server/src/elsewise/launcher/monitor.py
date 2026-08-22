import contextlib
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, cast

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from elsewise.runtime.controller import DaemonController, ServerStatus

MonitorEvent = dict[str, Any]


class RuntimeMonitor:
    def __init__(
        self,
        controller: DaemonController,
        callback: Callable[[MonitorEvent], None],
    ) -> None:
        self.controller = controller
        self.callback = callback
        self._stop = threading.Event()
        self._refresh = threading.Event()
        self._thread: threading.Thread | None = None
        self._websocket_lock = threading.Lock()
        self._websocket: ClientConnection | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="elsewise-runtime-monitor", daemon=True
        )
        self._thread.start()

    def request_refresh(self) -> None:
        self._refresh.set()
        self._close_websocket()

    def stop(self) -> None:
        self._stop.set()
        self._refresh.set()
        self._close_websocket()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            # A refresh interrupts an active WebSocket. Consume the flag before
            # reconnecting; otherwise every new socket exits immediately and the
            # monitor spins in a reconnect loop.
            self._refresh.clear()
            status = self.controller.status()
            self.callback({"kind": "lifecycle", "status": status})
            if status.state == "running" and status.url:
                if self._run_websocket(status.url):
                    continue
                payload = self._poll(status.url)
                if payload is not None:
                    self.callback({"kind": "runtime", "payload": payload})
            delay = (
                0.5
                if status.state in {"starting", "stopping"}
                else (2.0 if status.state in {"running", "unresponsive"} else 4.0)
            )
            self._refresh.wait(delay)
            self._refresh.clear()

    def _run_websocket(self, url: str) -> bool:
        websocket_url = url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        try:
            with connect(
                f"{websocket_url}/ws/runtime",
                open_timeout=1.5,
                close_timeout=0.5,
            ) as websocket:
                with self._websocket_lock:
                    self._websocket = websocket
                try:
                    while not self._stop.is_set() and not self._refresh.is_set():
                        try:
                            raw = websocket.recv(timeout=2.0)
                        except TimeoutError:
                            continue
                        if not isinstance(raw, str):
                            continue
                        message = json.loads(raw)
                        if isinstance(message, dict) and message.get("type") == "runtime.status":
                            payload = message.get("payload")
                            if isinstance(payload, dict):
                                self.callback(
                                    {
                                        "kind": "runtime",
                                        "payload": cast(dict[str, Any], payload),
                                    }
                                )
                finally:
                    with self._websocket_lock:
                        if self._websocket is websocket:
                            self._websocket = None
                return True
        except (OSError, ValueError, json.JSONDecodeError, WebSocketException):
            return self._refresh.is_set() or self._stop.is_set()

    def _close_websocket(self) -> None:
        with self._websocket_lock:
            websocket = self._websocket
        if websocket is not None:
            with contextlib.suppress(OSError, TimeoutError, WebSocketException):
                websocket.close()

    @staticmethod
    def _poll(url: str) -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(f"{url}/api/runtime/status", timeout=1.0) as response:
                value = json.loads(response.read().decode("utf-8"))
                return cast(dict[str, Any], value) if isinstance(value, dict) else None
        except (OSError, ValueError, urllib.error.URLError):
            return None


class LifecycleActionRunner:
    def __init__(self, callback: Callable[[ServerStatus], None]) -> None:
        self.callback = callback
        self._lock = threading.Lock()

    def run(self, action: Callable[[], ServerStatus]) -> bool:
        if not self._lock.acquire(blocking=False):
            return False

        def execute() -> None:
            try:
                result = action()
            except Exception as exc:
                result = ServerStatus("error", message=str(exc))
            finally:
                self._lock.release()
            self.callback(result)

        threading.Thread(target=execute, name="elsewise-lifecycle-action", daemon=True).start()
        return True
