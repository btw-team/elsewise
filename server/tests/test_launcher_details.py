import threading
from pathlib import Path

import pytest
from elsewise.launcher.log_viewer import LogTailWorker
from elsewise.launcher.notifications import NativeNotifier


def test_log_tail_is_incremental_bounded_and_refreshable(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    path.write_text("".join(f"line {index}\n" for index in range(1100)), encoding="utf-8")
    received: list[tuple[list[str], bool]] = []
    ready = threading.Event()

    def callback(lines: list[str], reset: bool) -> None:
        received.append((lines, reset))
        ready.set()

    worker = LogTailWorker(path, callback, initial_lines=1000)
    worker.start()
    try:
        assert ready.wait(timeout=2)
        initial, reset = received[-1]
        assert reset is True
        assert len(initial) == 1000
        assert initial[0] == "line 100\n"

        ready.clear()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("new line\n")
        assert ready.wait(timeout=2)
        assert received[-1] == (["new line\n"], False)

        ready.clear()
        worker.refresh()
        assert ready.wait(timeout=2)
        assert received[-1][1] is True
        assert len(received[-1][0]) == 1000
    finally:
        worker.stop()


def test_native_notification_falls_back_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback: list[tuple[str, str]] = []
    notifier = NativeNotifier(lambda title, message: fallback.append((title, message)))
    monkeypatch.setattr(
        NativeNotifier, "_send_native", staticmethod(lambda _title, _message: False)
    )

    assert notifier.send_once("event", "Title", "Message") is False
    assert notifier.send_once("event", "Title", "Message") is True
    assert fallback == [("Title", "Message")]
