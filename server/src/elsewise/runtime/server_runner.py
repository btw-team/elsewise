import argparse
import asyncio
import contextlib
import logging
import os
import threading
from secrets import token_urlsafe

import psutil
import uvicorn

from elsewise import __version__
from elsewise.main import create_app
from elsewise.runtime.descriptor import RuntimeDescriptor, RuntimeDescriptorStore, utc_iso
from elsewise.runtime.locking import FileLock, LockUnavailableError
from elsewise.runtime.logging import configure_server_logging
from elsewise.runtime.signals import shutdown_signal_handlers
from elsewise.settings.launcher import LauncherSettingsStore
from elsewise.settings.paths import AppPaths

_LOGGER = logging.getLogger("elsewise.runtime.server_runner")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=38473)
    return parser


async def run_server(
    *,
    paths: AppPaths,
    host: str,
    port: int,
    shutdown_requested: threading.Event | None = None,
) -> int:
    lock = FileLock(paths.runtime / "server.lock")
    try:
        lock.acquire(blocking=False)
    except LockUnavailableError:
        _LOGGER.error("Another Elsewise server already owns the runtime lock")
        return 2

    descriptor_store = RuntimeDescriptorStore(paths.runtime / "server.json")
    token_path = paths.runtime / "control-token"
    if not token_path.is_file():
        file_descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(token_urlsafe(32))
            handle.write("\n")
    process = psutil.Process(os.getpid())
    create_time = process.create_time()
    application = create_app(app_paths=paths)
    config = uvicorn.Config(
        application,
        host=host,
        port=port,
        log_config=None,
        access_log=True,
    )
    server = uvicorn.Server(config)
    application.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    task: asyncio.Task[None] | None = None
    shutdown_watcher: asyncio.Task[None] | None = None
    try:
        if shutdown_requested is not None:
            shutdown_watcher = asyncio.create_task(
                _watch_for_shutdown(server, shutdown_requested),
                name="elsewise-signal-watcher",
            )
        task = asyncio.create_task(server.serve(), name="elsewise-uvicorn")
        while not server.started and not task.done():
            await asyncio.sleep(0.05)
        if not server.started:
            await task
            return 1
        descriptor_store.save(
            RuntimeDescriptor(
                pid=os.getpid(),
                process_create_time=create_time,
                process_started_at=utc_iso(create_time),
                server_started_at=utc_iso(),
                version=__version__,
                url=f"http://{host}:{port}",
            )
        )
        _LOGGER.info("Server ready url=http://%s:%s", host, port)
        await task
        return 0
    finally:
        if shutdown_watcher is not None:
            shutdown_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shutdown_watcher
        if task is not None and not task.done():
            server.should_exit = True
            with contextlib.suppress(asyncio.CancelledError):
                await task
        current = descriptor_store.load()
        if (
            current is not None
            and current.pid == os.getpid()
            and abs(current.process_create_time - create_time) < 0.01
        ):
            descriptor_store.remove()
            with contextlib.suppress(FileNotFoundError):
                token_path.unlink()
        lock.release()


async def _watch_for_shutdown(server: uvicorn.Server, requested: threading.Event) -> None:
    while not requested.is_set():
        await asyncio.sleep(0.05)
    server.should_exit = True


def run_server_process(*, paths: AppPaths, host: str, port: int) -> int:
    shutdown_requested = threading.Event()
    with shutdown_signal_handlers(lambda _signal: shutdown_requested.set()):
        try:
            return asyncio.run(
                run_server(
                    paths=paths,
                    host=host,
                    port=port,
                    shutdown_requested=shutdown_requested,
                )
            )
        except KeyboardInterrupt:
            # Defensive fallback for platforms where a console handler races with
            # Uvicorn while it restores the process signal handlers.
            return 0


def main() -> None:
    arguments = build_parser().parse_args()
    paths = AppPaths.resolve(ensure_exists=True)
    launcher_settings = LauncherSettingsStore(paths.config / "launcher.json").load()
    configure_server_logging(paths.diagnostics, launcher_settings.server_log_total_limit_mb)
    raise SystemExit(run_server_process(paths=paths, host=arguments.host, port=arguments.port))


if __name__ == "__main__":
    main()
