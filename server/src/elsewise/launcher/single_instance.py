import contextlib
import json
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from secrets import token_urlsafe

import psutil

from elsewise.runtime.locking import FileLock, LockUnavailableError


class LauncherSingleInstance:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.lock = FileLock(runtime_dir / "launcher.lock")
        self.descriptor_path = runtime_dir / "launcher.json"
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._token = ""

    def acquire(self) -> bool:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.lock.acquire(blocking=False)
        except LockUnavailableError:
            return False
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(0.25)
        self._socket = listener
        self._token = token_urlsafe(24)
        self.descriptor_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "process_create_time": psutil.Process().create_time(),
                    "port": listener.getsockname()[1],
                    "token": self._token,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            self.descriptor_path.chmod(0o600)
        return True

    def notify_existing(self) -> bool:
        try:
            descriptor = json.loads(self.descriptor_path.read_text(encoding="utf-8"))
            pid = int(descriptor["pid"])
            created = float(descriptor["process_create_time"])
            process = psutil.Process(pid)
            if abs(process.create_time() - created) >= 0.01:
                return False
            port = int(descriptor["port"])
            token = str(descriptor["token"])
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as client:
                client.sendall(f"{token}\n".encode())
            return True
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, psutil.Error):
            return False

    def start_listener(self, callback: Callable[[], None]) -> None:
        if self._socket is None:
            raise RuntimeError("Launcher instance lock has not been acquired")

        def listen() -> None:
            assert self._socket is not None
            while not self._stop.is_set():
                try:
                    connection, _ = self._socket.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with connection, contextlib.suppress(OSError):
                    payload = connection.recv(256).decode().strip()
                    if payload == self._token:
                        callback()

        self._thread = threading.Thread(
            target=listen, name="elsewise-launcher-activation", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        with contextlib.suppress(FileNotFoundError):
            self.descriptor_path.unlink()
        self.lock.release()

    def __enter__(self) -> "LauncherSingleInstance":
        if not self.acquire():
            raise LockUnavailableError(str(self.lock.path))
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
