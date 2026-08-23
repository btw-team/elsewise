#!/usr/bin/env python3
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from plistlib import load as load_plist
from uuid import uuid4

from PyInstaller.archive.readers import CArchiveReader
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist/frozen/Elsewise"


def executable(name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return BUNDLE / f"{name}{suffix}"


def gui_archive_executable() -> Path:
    return executable("elsewise-gui")


def gui_smoke_executable() -> Path:
    if sys.platform == "darwin":
        app = ROOT / "dist/frozen/Elsewise.app"
        with (app / "Contents/Info.plist").open("rb") as plist_file:
            executable_name = load_plist(plist_file).get("CFBundleExecutable")
        if executable_name != "elsewise-gui":
            raise RuntimeError(
                f"Frozen macOS bundle has an invalid CFBundleExecutable: {executable_name!r}"
            )
        return app / "Contents/MacOS" / executable_name
    return gui_archive_executable()


def isolated_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name, directory in {
        "ELSEWISE_DATA_DIR": root / "data",
        "ELSEWISE_CONFIG_DIR": root / "config",
        "ELSEWISE_CACHE_DIR": root / "cache",
        "ELSEWISE_RUNTIME_DIR": root / "runtime",
        "ELSEWISE_DIAGNOSTICS_DIR": root / "logs",
    }.items():
        environment[name] = str(directory)
    return environment


def verify_gui_archive(gui: Path) -> None:
    archive = CArchiveReader(str(gui)).open_embedded_archive("PYZ.pyz")
    required = {"PIL.ImageTk", "PIL._tkinter_finder"}
    missing = sorted(required.difference(archive.toc))
    if missing:
        raise RuntimeError(f"Frozen GUI archive is missing required modules: {missing}")


def smoke_gui(gui: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="elsewise-frozen-gui-smoke-") as temporary:
        root = Path(temporary)
        environment = isolated_environment(root)
        environment["ELSEWISE_FROZEN_GUI_SMOKE_TEST"] = "1"
        command = [str(gui)]
        if sys.platform.startswith("linux") and not environment.get("DISPLAY"):
            xvfb_run = shutil.which("xvfb-run")
            if xvfb_run is None:
                raise RuntimeError("xvfb-run is required to smoke-test the frozen GUI")
            command = [xvfb_run, "-a", *command]
        result = subprocess.run(
            command,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            log_path = root / "logs/launcher.log"
            launcher_log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
            raise RuntimeError(
                "Frozen GUI smoke test failed with exit code "
                f"{result.returncode}.\nstdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}\nlauncher.log:\n{launcher_log}"
            )


def wait_for_health(port: int, timeout: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=1.0
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Frozen server did not become ready")


def available_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def smoke_ingest_protocol(root: Path, port: int, version: str) -> None:
    pairing_path = root / "config/pairing.json"
    pairing = json.loads(pairing_path.read_text(encoding="utf-8"))
    with connect(
        f"ws://127.0.0.1:{port}/ws/ingest",
        origin="chrome-extension://abcdefghijklmnopabcdefghijklmnop",
        open_timeout=3,
        close_timeout=1,
    ) as websocket:
        websocket.send(
            json.dumps(
                {
                    "type": "client.hello",
                    "protocol_version": 1,
                    "role": "extension",
                    "token": pairing["token"],
                    "installation_id": str(uuid4()),
                    "extension_version": version,
                }
            )
        )
        response = json.loads(websocket.recv(timeout=3))
        if response.get("type") != "server.hello":
            raise RuntimeError(f"Frozen ingest handshake failed: {response}")


def main() -> None:
    cli = executable("elsewise")
    gui_archive = gui_archive_executable()
    gui_smoke = gui_smoke_executable()
    required = (
        cli,
        gui_archive,
        gui_smoke,
        executable("elsewise-server"),
        BUNDLE / "_internal/elsewise/web_dist/index.html",
        BUNDLE / "_internal/elsewise/migrations/versions/0001_initial.py",
        BUNDLE / "_internal/elsewise/protocol/schema_files/client.hello.schema.json",
        BUNDLE / "_internal/elsewise/assets/elsewise-logo-dark.png",
        BUNDLE / "_internal/elsewise/assets/elsewise-logo-light.png",
        BUNDLE / "_internal/elsewise/assets/theme-tokens.json",
        BUNDLE / "_internal/elsewise/assets/external-links.json",
        BUNDLE / "_internal/certifi/cacert.pem",
        BUNDLE / "_internal/LICENSE",
        BUNDLE / "_internal/NOTICE",
        BUNDLE / "_internal/THIRD_PARTY_NOTICES.md",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Frozen bundle is missing required files: {missing}")
    verify_gui_archive(gui_archive)
    smoke_gui(gui_smoke)

    with tempfile.TemporaryDirectory(prefix="elsewise-frozen-smoke-") as temporary:
        root = Path(temporary)
        environment = isolated_environment(root)
        version = subprocess.run(
            [cli, "--version"], env=environment, check=True, capture_output=True, text=True
        ).stdout.strip()
        port = available_port()
        server_log_path = root / "server-smoke.log"
        with server_log_path.open("wb") as server_log:
            server = subprocess.Popen(
                [executable("elsewise-server"), "--host", "127.0.0.1", "--port", str(port)],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=server_log,
                stderr=subprocess.STDOUT,
            )
            try:
                health = wait_for_health(port)
                if health.get("version") != version:
                    raise RuntimeError(f"Frozen version mismatch: {health} != {version}")
                smoke_ingest_protocol(root, port, version)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2.0) as response:
                    if b'<div id="root"></div>' not in response.read():
                        raise RuntimeError("Frozen web GUI entry point was not served")
            except Exception as exc:
                server_log.flush()
                output = server_log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(
                    f"Frozen server smoke test failed.\nserver.log:\n{output}"
                ) from exc
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
    print(f"Verified frozen Elsewise {version}")


if __name__ == "__main__":
    main()
