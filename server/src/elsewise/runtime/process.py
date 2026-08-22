import contextlib
import os
import subprocess
import sys
from pathlib import Path
from typing import IO

import psutil

from elsewise.runtime.descriptor import RuntimeDescriptor
from elsewise.settings.paths import AppPaths


def process_matches(descriptor: RuntimeDescriptor) -> bool:
    try:
        process = psutil.Process(descriptor.pid)
        return (
            process.is_running()
            and process.status() != psutil.STATUS_ZOMBIE
            and abs(process.create_time() - descriptor.process_create_time) < 0.01
        )
    except (psutil.Error, OSError):
        return False


def process_create_time(pid: int) -> float:
    return psutil.Process(pid).create_time()


def port_owner(host: str, port: int) -> tuple[int | None, str | None]:
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if not connection.laddr or connection.laddr.port != port:
                continue
            if connection.laddr.ip not in {host, "0.0.0.0", "::", "::1"}:
                continue
            if connection.pid is None:
                return None, None
            with contextlib.suppress(psutil.Error):
                return connection.pid, psutil.Process(connection.pid).name()
            return connection.pid, None
    except (psutil.Error, OSError):
        pass
    return None, None


def packaged_server_executable() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    candidates = (
        executable.parent / "internal" / "elsewise-server.exe",
        executable.parent / "internal" / "elsewise-server",
        executable.parent / "elsewise-server.exe",
        executable.parent / "elsewise-server",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def server_command(*, host: str, port: int) -> list[str]:
    packaged = packaged_server_executable()
    command = (
        [str(packaged)]
        if packaged is not None
        else [
            sys.executable,
            "-m",
            "elsewise.runtime.server_runner",
        ]
    )
    return [*command, "--host", host, "--port", str(port)]


def launch_server(
    *,
    paths: AppPaths,
    host: str,
    port: int,
    output: IO[bytes],
) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment.update(paths.environment())
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        return subprocess.Popen(
            server_command(host=host, port=port),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=environment,
            close_fds=True,
            creationflags=creation_flags,
        )
    return subprocess.Popen(
        server_command(host=host, port=port),
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        env=environment,
        close_fds=True,
        start_new_session=True,
    )


def terminate_verified_process_tree(
    descriptor: RuntimeDescriptor,
    *,
    terminate_timeout: float,
    kill_timeout: float,
) -> str:
    if not process_matches(descriptor):
        return "already_stopped"
    try:
        parent = psutil.Process(descriptor.pid)
        processes = [*parent.children(recursive=True), parent]
        for process in reversed(processes):
            with contextlib.suppress(psutil.Error):
                process.terminate()
        _, alive = psutil.wait_procs(processes, timeout=terminate_timeout)
        if not alive:
            return "terminated"
        for process in alive:
            with contextlib.suppress(psutil.Error):
                process.kill()
        _, alive = psutil.wait_procs(alive, timeout=kill_timeout)
        return "killed" if not alive else "failed"
    except psutil.Error:
        return "failed"
