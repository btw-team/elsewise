import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path


class LogTailWorker:
    def __init__(
        self,
        path: Path,
        callback: Callable[[list[str], bool], None],
        *,
        initial_lines: int = 1000,
    ) -> None:
        self.path = path
        self.callback = callback
        self.initial_lines = initial_lines
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._refresh = threading.Event()
        self._thread: threading.Thread | None = None
        self._position = 0
        self._identity: tuple[int, int] | None = None
        self._initialized = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="elsewise-log-tail", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._refresh.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
            self._refresh.set()

    def refresh(self) -> None:
        self._initialized = False
        self._position = 0
        self._identity = None
        self._refresh.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._paused.is_set():
                lines, reset = self._read_available()
                if lines:
                    self.callback(lines, reset)
            self._refresh.wait(0.4)
            self._refresh.clear()

    def _read_available(self) -> tuple[list[str], bool]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._initialized = False
            self._position = 0
            self._identity = None
            return [], False
        identity = (stat.st_dev, stat.st_ino)
        if not self._initialized or self._identity != identity or stat.st_size < self._position:
            recent: deque[str] = deque(maxlen=self.initial_lines)
            with self.path.open(encoding="utf-8", errors="replace") as handle:
                recent.extend(handle)
                self._position = handle.tell()
            self._identity = identity
            self._initialized = True
            return list(recent), True
        with self.path.open(encoding="utf-8", errors="replace") as handle:
            handle.seek(self._position)
            lines = handle.readlines()
            self._position = handle.tell()
        return lines, False
