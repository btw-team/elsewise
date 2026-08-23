import contextlib
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any, Literal, cast

from elsewise import __version__
from elsewise.runtime.descriptor import (
    RuntimeDescriptor,
    RuntimeDescriptorStore,
    utc_iso,
)
from elsewise.runtime.locking import FileLock, LockUnavailableError
from elsewise.runtime.process import (
    launch_server,
    port_owner,
    process_create_time,
    process_matches,
    terminate_verified_process_tree,
)
from elsewise.settings.launcher import LauncherSettingsStore
from elsewise.settings.paths import AppPaths

LifecycleState = Literal[
    "stopped",
    "starting",
    "running",
    "stopping",
    "unresponsive",
    "port_conflict",
    "error",
]

_LOGGER = logging.getLogger("elsewise.runtime.controller")


@dataclass(frozen=True, slots=True)
class ServerStatus:
    state: LifecycleState
    pid: int | None = None
    version: str | None = None
    url: str | None = None
    uptime_seconds: float | None = None
    message: str | None = None
    escalation: str | None = None


class DaemonController:
    def __init__(
        self,
        paths: AppPaths | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 38473,
        start_timeout: float = 20.0,
        stop_timeout: float = 15.0,
        terminate_timeout: float = 5.0,
        kill_timeout: float = 3.0,
    ) -> None:
        self.paths = paths or AppPaths.resolve(ensure_exists=True)
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.terminate_timeout = terminate_timeout
        self.kill_timeout = kill_timeout
        self.lifecycle_lock = FileLock(self.paths.runtime / "lifecycle.lock")
        self.descriptors = RuntimeDescriptorStore(self.paths.runtime / "server.json")
        self.token_path = self.paths.runtime / "control-token"

    def _health(self, url: str | None = None, *, timeout: float = 0.75) -> bool:
        try:
            with urllib.request.urlopen(
                f"{url or self.url}/api/health", timeout=timeout
            ) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                return isinstance(payload, dict) and payload.get("status") == "ok"
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def _port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.settimeout(0.2)
            return candidate.connect_ex((self.host, self.port)) == 0

    def status(self) -> ServerStatus:
        descriptor = self.descriptors.load()
        if descriptor is not None:
            if process_matches(descriptor):
                if self._health(descriptor.url):
                    try:
                        started = datetime.fromisoformat(
                            descriptor.server_started_at.replace("Z", "+00:00")
                        )
                        uptime = max(0.0, (datetime.now(UTC) - started).total_seconds())
                    except ValueError:
                        uptime = None
                    return ServerStatus(
                        "running",
                        descriptor.pid,
                        descriptor.version,
                        descriptor.url,
                        uptime,
                    )
                state: LifecycleState = (
                    "starting" if not descriptor.server_started_at else "unresponsive"
                )
                return ServerStatus(
                    state,
                    descriptor.pid,
                    descriptor.version,
                    descriptor.url,
                    message="Server process is alive but the health endpoint is unavailable.",
                )
            self.descriptors.remove()
            self._remove_token()
        if self._port_in_use():
            owner_pid, owner_name = port_owner(self.host, self.port)
            owner = (
                f" PID {owner_pid} ({owner_name})."
                if owner_pid is not None and owner_name
                else f" PID {owner_pid}."
                if owner_pid is not None
                else ""
            )
            return ServerStatus(
                "port_conflict",
                pid=owner_pid,
                url=self.url,
                message=f"Port {self.port} is owned by another process.{owner}",
            )
        return ServerStatus("stopped", url=self.url)

    def start(self) -> ServerStatus:
        self.paths = self.paths
        for directory in (
            self.paths.data,
            self.paths.config,
            self.paths.cache,
            self.paths.runtime,
            self.paths.diagnostics,
            self.paths.exports,
            self.paths.agent_empty_cwd,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lifecycle_lock:
                current = self.status()
                if current.state in {"running", "starting"}:
                    return current
                if current.state == "port_conflict":
                    return current
                self._write_token(token_urlsafe(32))
                output_path = self.paths.diagnostics / "server.log"
                output = output_path.open("ab", buffering=0)
                try:
                    process = launch_server(
                        paths=self.paths,
                        host=self.host,
                        port=self.port,
                        output=output,
                    )
                finally:
                    output.close()
                create_time = process_create_time(process.pid)
                self.descriptors.save(
                    RuntimeDescriptor(
                        pid=process.pid,
                        process_create_time=create_time,
                        process_started_at=utc_iso(create_time),
                        server_started_at="",
                        version=__version__,
                        url=self.url,
                    )
                )
                deadline = time.monotonic() + self.start_timeout
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.descriptors.remove()
                        self._remove_token()
                        return ServerStatus(
                            "error",
                            process.pid,
                            __version__,
                            self.url,
                            message=f"Server exited during startup with code {process.returncode}.",
                        )
                    state = self.status()
                    if state.state == "running":
                        return state
                    time.sleep(0.1)
                return ServerStatus(
                    "unresponsive",
                    process.pid,
                    __version__,
                    self.url,
                    message="Server did not become ready before the startup timeout.",
                )
        except LockUnavailableError:
            return ServerStatus(
                "error", url=self.url, message="Another lifecycle action is running."
            )
        except (OSError, RuntimeError) as exc:
            _LOGGER.exception("Unable to start server")
            return ServerStatus("error", url=self.url, message=str(exc))

    def stop(self) -> ServerStatus:
        try:
            with self.lifecycle_lock:
                current = self.status()
                if current.state == "stopped":
                    return current
                if current.state == "port_conflict":
                    return current
                descriptor = self.descriptors.load()
                if descriptor is None or not process_matches(descriptor):
                    return self.status()
                token = self._read_token()
                requested = False
                deadline = time.monotonic() + self.stop_timeout
                while time.monotonic() < deadline:
                    if not process_matches(descriptor):
                        self.descriptors.remove()
                        self._remove_token()
                        return ServerStatus("stopped", url=self.url)
                    if token and not requested:
                        requested = self._request_shutdown(descriptor.url, token)
                    time.sleep(0.1)
                return ServerStatus(
                    "unresponsive",
                    descriptor.pid,
                    descriptor.version,
                    descriptor.url,
                    message="Graceful shutdown timed out; explicit force stop is required.",
                )
        except LockUnavailableError:
            return ServerStatus(
                "error", url=self.url, message="Another lifecycle action is running."
            )

    def force_stop(self) -> ServerStatus:
        try:
            with self.lifecycle_lock:
                descriptor = self.descriptors.load()
                if descriptor is None:
                    return self.status()
                escalation = terminate_verified_process_tree(
                    descriptor,
                    terminate_timeout=self.terminate_timeout,
                    kill_timeout=self.kill_timeout,
                )
                if not process_matches(descriptor):
                    self.descriptors.remove()
                    self._remove_token()
                    _LOGGER.warning("Forced server shutdown stage=%s", escalation)
                    return ServerStatus("stopped", url=self.url, escalation=escalation)
                return ServerStatus(
                    "error",
                    descriptor.pid,
                    descriptor.version,
                    descriptor.url,
                    message="Unable to terminate the verified server process tree.",
                    escalation=escalation,
                )
        except LockUnavailableError:
            return ServerStatus(
                "error", url=self.url, message="Another lifecycle action is running."
            )

    def restart(self, *, force: bool = False) -> ServerStatus:
        stopped = self.stop()
        if stopped.state == "unresponsive" and force:
            stopped = self.force_stop()
        if stopped.state not in {"stopped"}:
            return stopped
        return self.start()

    def set_agent_drain(self, enabled: bool) -> bool:
        current = self.status()
        token = self._read_token()
        if current.state != "running" or not current.url or not token:
            return False
        return self._control_post(
            f"{current.url}/api/runtime/agent-drain?enabled={'true' if enabled else 'false'}",
            token,
        )

    def runtime_status_payload(self) -> dict[str, Any] | None:
        current = self.status()
        if current.state != "running" or not current.url:
            return None
        try:
            with urllib.request.urlopen(
                f"{current.url}/api/runtime/status", timeout=1.0
            ) as response:
                value = json.loads(response.read().decode("utf-8"))
                return cast(dict[str, Any], value) if isinstance(value, dict) else None
        except (OSError, ValueError, urllib.error.URLError):
            return None

    def open_web_gui(self) -> bool:
        if self.status().state != "running":
            return False
        return webbrowser.open(self.url)

    def _write_token(self, token: str) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.write("\n")
        with contextlib.suppress(OSError):
            self.token_path.chmod(0o600)

    def _read_token(self) -> str | None:
        try:
            return self.token_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _remove_token(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.token_path.unlink()

    @staticmethod
    def _request_shutdown(url: str, token: str) -> bool:
        return DaemonController._control_post(f"{url}/api/runtime/shutdown", token)

    @staticmethod
    def _control_post(url: str, token: str) -> bool:
        request = urllib.request.Request(
            url,
            method="POST",
            headers={"X-Elsewise-Control-Token": token},
        )
        try:
            with urllib.request.urlopen(request, timeout=0.5) as response:
                return int(response.status) == 200
        except (OSError, urllib.error.URLError):
            return False

    def configured_log_limit_mb(self) -> int:
        settings = LauncherSettingsStore(self.paths.config / "launcher.json").load()
        return settings.server_log_total_limit_mb
