import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from elsewise.runtime.controller import DaemonController
from elsewise.runtime.descriptor import RuntimeDescriptor, RuntimeDescriptorStore, utc_iso
from elsewise.runtime.locking import FileLock, LockUnavailableError
from elsewise.runtime.logging import ParticipantNameRedactor, configure_server_logging
from elsewise.runtime.process import process_create_time, process_matches
from elsewise.runtime.signals import shutdown_signal_handlers
from elsewise.settings.launcher import (
    LauncherSettings,
    LauncherSettingsStore,
)
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


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def test_launcher_settings_defaults_and_atomic_validation(tmp_path: Path) -> None:
    store = LauncherSettingsStore(tmp_path / "launcher.json")

    assert store.load() == LauncherSettings()
    updated = store.update(server_log_total_limit_mb=100, stop_server_on_exit=True)

    assert updated.server_log_total_limit_mb == 100
    assert updated.stop_server_on_exit is True
    assert store.load() == updated
    with pytest.raises(ValueError, match="Unsupported server log limit"):
        store.update(server_log_total_limit_mb=12)


def test_launcher_settings_recovers_invalid_json_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    path.write_text("not json", encoding="utf-8")

    assert LauncherSettingsStore(path).load() == LauncherSettings()
    assert (
        LauncherSettings.model_validate_json(path.read_text(encoding="utf-8")) == LauncherSettings()
    )
    assert path.with_name("launcher.json.bak").is_file()


def test_file_lock_rejects_second_nonblocking_owner(tmp_path: Path) -> None:
    first = FileLock(tmp_path / "runtime.lock")
    second = FileLock(tmp_path / "runtime.lock")
    first.acquire()
    try:
        with pytest.raises(LockUnavailableError):
            second.acquire(blocking=False)
    finally:
        first.release()


def test_shutdown_signal_handler_is_scoped_and_restored() -> None:
    received: list[signal.Signals] = []
    previous = signal.getsignal(signal.SIGINT)

    with shutdown_signal_handlers(received.append):
        installed: Any = signal.getsignal(signal.SIGINT)
        assert callable(installed)
        installed(signal.SIGINT, None)

    assert received == [signal.SIGINT]
    assert signal.getsignal(signal.SIGINT) == previous


def test_descriptor_round_trip_and_process_identity(tmp_path: Path) -> None:
    create_time = process_create_time(os.getpid())
    descriptor = RuntimeDescriptor(
        pid=os.getpid(),
        process_create_time=create_time,
        process_started_at=utc_iso(create_time),
        server_started_at=utc_iso(),
        version="test",
        url="http://127.0.0.1:1",
    )
    store = RuntimeDescriptorStore(tmp_path / "server.json")
    store.save(descriptor)

    assert store.load() == descriptor
    assert process_matches(descriptor) is True
    assert (
        process_matches(
            RuntimeDescriptor(
                pid=descriptor.pid,
                process_create_time=descriptor.process_create_time - 10,
                process_started_at=descriptor.process_started_at,
                server_started_at=descriptor.server_started_at,
                version=descriptor.version,
                url=descriptor.url,
            )
        )
        is False
    )


def test_server_logging_rotates_with_five_file_bound(tmp_path: Path) -> None:
    configure_server_logging(tmp_path, total_limit_mb=1)
    logger = logging.getLogger("elsewise.test.rotation")
    for _ in range(5000):
        logger.info("x" * 250)
    for handler in logging.getLogger().handlers:
        handler.flush()

    files = sorted(tmp_path.glob("server.log*"))
    assert 1 < len(files) <= 5
    assert sum(path.stat().st_size for path in files) <= 1_200_000


def test_participant_names_are_replaced_with_session_scoped_aliases() -> None:
    redactor = ParticipantNameRedactor()

    assert redactor.register("session-a", "Evgenii Gerasimenko") == "Participant 1"
    assert redactor.register("session-a", "Chu Kimba") == "Participant 2"
    assert redactor.register("session-b", "Chu Kimba") == "Participant 1"
    assert redactor.redact("Evgenii Gerasimenko spoke to Chu Kimba") == (
        "Participant 1 spoke to Participant 2"
    )

    redactor.forget_session("session-a")
    assert redactor.redact("Evgenii Gerasimenko") == "Evgenii Gerasimenko"


def test_participant_redactor_filters_logging_arguments() -> None:
    redactor = ParticipantNameRedactor()
    redactor.register("session-a", "Sensitive Name")
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "speaker=%(speaker)s",
        ({"speaker": "Sensitive Name"},),
        None,
    )

    assert redactor.filter(record)
    assert record.getMessage() == "speaker=Participant 1"


def test_controller_reports_port_conflict_without_replacing_owner(tmp_path: Path) -> None:
    paths = app_paths(tmp_path)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        port = int(owner.getsockname()[1])
        controller = DaemonController(paths, port=port)

        status = controller.start()

        assert status.state == "port_conflict"
        assert owner.fileno() >= 0


@pytest.mark.integration
def test_controller_starts_and_stops_independent_server(tmp_path: Path) -> None:
    paths = app_paths(tmp_path)
    controller = DaemonController(
        paths,
        port=available_port(),
        start_timeout=15,
        stop_timeout=15,
        terminate_timeout=2,
        kill_timeout=2,
    )
    try:
        started = controller.start()
        assert started.state == "running", started
        assert started.pid is not None and started.pid != os.getpid()
        assert controller.status().state == "running"
        assert (paths.runtime / "control-token").stat().st_mode & 0o077 == 0
        assert controller.set_agent_drain(True) is True
        payload = controller.runtime_status_payload()
        assert payload is not None and payload["agent_work"]["draining"] is True
        assert controller.set_agent_drain(False) is True

        restarted = controller.restart()
        assert restarted.state == "running", restarted
        assert restarted.pid is not None and restarted.pid != started.pid

        stopped = controller.stop()
        assert stopped.state == "stopped", stopped
        assert controller.status().state == "stopped"
        assert not (paths.runtime / "server.json").exists()
        assert not (paths.runtime / "control-token").exists()
    finally:
        if controller.status().state != "stopped":
            controller.force_stop()


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="Windows console signals need native packaging QA")
def test_foreground_server_sigint_is_clean_and_releases_runtime_state(tmp_path: Path) -> None:
    paths = app_paths(tmp_path)
    port = available_port()
    controller = DaemonController(paths, port=port)
    environment = os.environ.copy()
    environment.update(paths.environment())
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "elsewise.runtime.server_runner",
            "--port",
            str(port),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and controller.status().state != "running":
            if process.poll() is not None:
                break
            time.sleep(0.1)
        assert controller.status().state == "running"

        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=20)

        assert process.returncode == 0
        assert stdout == ""
        assert stderr == ""
        assert controller.status().state == "stopped"
        assert not (paths.runtime / "server.json").exists()
        assert not (paths.runtime / "control-token").exists()
        with FileLock(paths.runtime / "server.lock"):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
