#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    run(NPM, "run", "build", "--workspace", "web")
    run(sys.executable, "scripts/prepare-packaging-assets.py")
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        "dist/frozen",
        "--workpath",
        "build/pyinstaller",
        "packaging/elsewise.spec",
    )
    run(sys.executable, "scripts/verify-frozen.py")


if __name__ == "__main__":
    main()
