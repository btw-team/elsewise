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

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist/frozen/Elsewise"


def executable(name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return BUNDLE / f"{name}{suffix}"


def gui_executable() -> Path:
    name = "Elsewise" if sys.platform in {"darwin", "win32"} else "elsewise-gui"
    return executable(name)


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
        environment = isolated_environment(Path(temporary))
        environment["ELSEWISE_FROZEN_GUI_SMOKE_TEST"] = "1"
        command = [str(gui)]
        if sys.platform.startswith("linux") and not environment.get("DISPLAY"):
            xvfb_run = shutil.which("xvfb-run")
            if xvfb_run is None:
                raise RuntimeError("xvfb-run is required to smoke-test the frozen GUI")
            command = [xvfb_run, "-a", *command]
        subprocess.run(command, env=environment, check=True, timeout=30)


def wait_for_health(timeout: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:38473/api/health", timeout=1.0
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Frozen server did not become ready")


def ensure_port_available() -> None:
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 38473)) == 0:
            raise RuntimeError("Port 38473 is already in use; refusing frozen smoke test")


def main() -> None:
    cli = executable("elsewise")
    gui = gui_executable()
    required = (
        cli,
        gui,
        executable("elsewise-server"),
        BUNDLE / "_internal/elsewise/web_dist/index.html",
        BUNDLE / "_internal/elsewise/migrations/versions/0001_initial.py",
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
    verify_gui_archive(gui)
    smoke_gui(gui)
    ensure_port_available()

    with tempfile.TemporaryDirectory(prefix="elsewise-frozen-smoke-") as temporary:
        root = Path(temporary)
        environment = isolated_environment(root)
        version = subprocess.run(
            [cli, "--version"], env=environment, check=True, capture_output=True, text=True
        ).stdout.strip()
        try:
            subprocess.run([cli, "start"], env=environment, check=True, timeout=30)
            health = wait_for_health()
            if health.get("version") != version:
                raise RuntimeError(f"Frozen version mismatch: {health} != {version}")
            with urllib.request.urlopen("http://127.0.0.1:38473/", timeout=2.0) as response:
                if b'<div id="root"></div>' not in response.read():
                    raise RuntimeError("Frozen web GUI entry point was not served")
        finally:
            subprocess.run([cli, "stop"], env=environment, check=False, timeout=30)
    print(f"Verified frozen Elsewise {version}")


if __name__ == "__main__":
    main()
