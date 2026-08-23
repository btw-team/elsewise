from io import StringIO
from pathlib import Path

import pytest
from elsewise import cli
from elsewise.runtime.controller import ServerStatus


class FakeController:
    def __init__(self, status: ServerStatus) -> None:
        self.result = status
        self.force_calls = 0

    def start(self) -> ServerStatus:
        return self.result

    def stop(self) -> ServerStatus:
        return self.result

    def force_stop(self) -> ServerStatus:
        self.force_calls += 1
        return ServerStatus("stopped", url="http://127.0.0.1:38473", escalation="terminated")

    def restart(self, *, force: bool = False) -> ServerStatus:
        _ = force
        return self.result

    def status(self) -> ServerStatus:
        return self.result

    def open_web_gui(self) -> bool:
        return self.result.state == "running"


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSEWISE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ELSEWISE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ELSEWISE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ELSEWISE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("ELSEWISE_DIAGNOSTICS_DIR", str(tmp_path / "diagnostics"))


def test_status_has_stable_human_readable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = FakeController(
        ServerStatus(
            "running",
            pid=123,
            version="0.1.2",
            url="http://127.0.0.1:38473",
            uptime_seconds=12.9,
        )
    )
    monkeypatch.setattr(cli, "_controller", lambda: controller)
    output = StringIO()

    result = cli.run_cli(["status"], output=output)

    assert result == cli.EXIT_OK
    assert output.getvalue() == (
        "running pid=123 url=http://127.0.0.1:38473 version=0.1.2 uptime=12s\n"
    )


def test_stop_requires_explicit_force_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = FakeController(ServerStatus("unresponsive", pid=123))
    monkeypatch.setattr(cli, "_controller", lambda: controller)

    assert cli.run_cli(["stop"], output=StringIO()) == cli.EXIT_FORCE_REQUIRED
    assert controller.force_calls == 0
    assert cli.run_cli(["stop", "--force"], output=StringIO()) == cli.EXIT_OK
    assert controller.force_calls == 1


def test_port_conflict_uses_unavailable_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = FakeController(ServerStatus("port_conflict", pid=321, message="occupied"))
    monkeypatch.setattr(cli, "_controller", lambda: controller)
    output = StringIO()

    assert cli.run_cli(["start"], output=output) == cli.EXIT_UNAVAILABLE
    assert "port_conflict pid=321" in output.getvalue()
    assert "occupied" in output.getvalue()


def test_logs_print_recent_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log_path = tmp_path / "diagnostics" / "server.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("first\nsecond\n", encoding="utf-8")
    output = StringIO()

    assert cli.run_cli(["logs"], output=output) == cli.EXIT_OK
    assert output.getvalue() == "first\nsecond\n"
    assert capsys.readouterr().err == ""
