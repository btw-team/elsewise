import contextlib
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

SignalCallback = Callable[[signal.Signals], None]


def _shutdown_signals() -> tuple[signal.Signals, ...]:
    requested = [signal.SIGINT, signal.SIGTERM]
    sigbreak = getattr(signal, "SIGBREAK", None)
    if isinstance(sigbreak, signal.Signals):
        requested.append(sigbreak)
    return tuple(dict.fromkeys(requested))


@contextmanager
def shutdown_signal_handlers(callback: SignalCallback) -> Iterator[None]:
    """Temporarily turn terminal/process shutdown signals into a callback."""

    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous: dict[signal.Signals, Any] = {}

    def handle(signum: int, _frame: object) -> None:
        callback(signal.Signals(signum))

    try:
        for requested in _shutdown_signals():
            try:
                previous[requested] = signal.signal(requested, handle)
            except (OSError, ValueError):
                continue
        yield
    finally:
        for requested, handler in previous.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(requested, handler)
