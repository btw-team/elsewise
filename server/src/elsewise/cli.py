import argparse
import sys
import time
from collections import deque
from pathlib import Path
from typing import TextIO

from elsewise import __version__
from elsewise.runtime.controller import DaemonController, ServerStatus
from elsewise.runtime.logging import configure_server_logging
from elsewise.runtime.server_runner import run_server_process
from elsewise.settings.launcher import LauncherSettingsStore
from elsewise.settings.paths import AppPaths

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNAVAILABLE = 2
EXIT_FORCE_REQUIRED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elsewise")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start", help="Start the server in the background")
    stop = commands.add_parser("stop", help="Stop the server")
    stop.add_argument("--force", action="store_true", help="Force stop after graceful timeout")
    restart = commands.add_parser("restart", help="Restart the server")
    restart.add_argument("--force", action="store_true", help="Force stop after graceful timeout")
    commands.add_parser("status", help="Show server status")
    commands.add_parser("open", help="Open the web GUI")
    logs = commands.add_parser("logs", help="Show recent server logs")
    logs.add_argument("--follow", action="store_true", help="Follow new log lines")
    commands.add_parser("run", help="Run the server in the foreground")
    return parser


def _controller() -> DaemonController:
    return DaemonController()


def _print_status(status: ServerStatus, output: TextIO) -> None:
    fields: list[str] = [status.state]
    if status.pid is not None:
        fields.append(f"pid={status.pid}")
    if status.url:
        fields.append(f"url={status.url}")
    if status.version:
        fields.append(f"version={status.version}")
    if status.uptime_seconds is not None:
        fields.append(f"uptime={int(status.uptime_seconds)}s")
    if status.escalation:
        fields.append(f"escalation={status.escalation}")
    print(" ".join(fields), file=output)
    if status.message:
        print(status.message, file=output)


def _status_exit(status: ServerStatus) -> int:
    if status.state in {"running", "stopped", "starting"}:
        return EXIT_OK
    if status.state == "unresponsive":
        return EXIT_FORCE_REQUIRED
    if status.state == "port_conflict":
        return EXIT_UNAVAILABLE
    return EXIT_ERROR


def _tail(path: Path, output: TextIO, *, lines: int = 200) -> None:
    if not path.is_file():
        print("No server log is available.", file=output)
        return
    recent: deque[str] = deque(maxlen=lines)
    with path.open(encoding="utf-8", errors="replace") as handle:
        recent.extend(handle)
    for line in recent:
        output.write(line)


def _follow(path: Path, output: TextIO) -> None:
    _tail(path, output, lines=50)
    position = path.stat().st_size if path.is_file() else 0
    identity: tuple[int, int] | None = None
    while True:
        try:
            stat = path.stat()
            current_identity = (stat.st_dev, stat.st_ino)
            if identity is None:
                identity = current_identity
            if current_identity != identity or stat.st_size < position:
                position = 0
                identity = current_identity
            with path.open(encoding="utf-8", errors="replace") as handle:
                handle.seek(position)
                chunk = handle.read()
                position = handle.tell()
            if chunk:
                output.write(chunk)
                output.flush()
        except FileNotFoundError:
            identity = None
            position = 0
        time.sleep(0.25)


def _run_foreground(paths: AppPaths) -> int:
    settings = LauncherSettingsStore(paths.config / "launcher.json").load()
    configure_server_logging(paths.diagnostics, settings.server_log_total_limit_mb)
    return run_server_process(paths=paths, host="127.0.0.1", port=38473)


def run_cli(
    argv: list[str] | None = None,
    *,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int:
    arguments = build_parser().parse_args(argv)
    paths = AppPaths.resolve(ensure_exists=True)
    if arguments.command == "run":
        return _run_foreground(paths)
    controller = _controller()
    if arguments.command == "start":
        status = controller.start()
    elif arguments.command == "stop":
        status = controller.stop()
        if status.state == "unresponsive" and arguments.force:
            status = controller.force_stop()
    elif arguments.command == "restart":
        status = controller.restart(force=arguments.force)
    elif arguments.command == "status":
        status = controller.status()
    elif arguments.command == "open":
        if controller.open_web_gui():
            print("Opened the Elsewise web GUI.", file=output)
            return EXIT_OK
        print("The Elsewise server is not running.", file=error)
        return EXIT_UNAVAILABLE
    elif arguments.command == "logs":
        log_path = paths.diagnostics / "server.log"
        try:
            if arguments.follow:
                _follow(log_path, output)
            else:
                _tail(log_path, output)
        except KeyboardInterrupt:
            return EXIT_OK
        return EXIT_OK
    else:  # pragma: no cover - argparse prevents this branch
        return EXIT_ERROR
    _print_status(status, output if status.state not in {"error"} else error)
    return _status_exit(status)


def main() -> None:
    try:
        result = run_cli()
    except KeyboardInterrupt:
        result = EXIT_OK
    raise SystemExit(result)


if __name__ == "__main__":
    main()
