# -*- mode: python ; coding: utf-8 -*-
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH).resolve().parent
WEB_DIST = ROOT / "web" / "dist"
ASSETS = ROOT / "web" / "src" / "assets"
MIGRATIONS = ROOT / "server" / "src" / "elsewise" / "migrations"
GENERATED = ROOT / "packaging" / "generated"
with (ROOT / "pyproject.toml").open("rb") as version_file:
    PRODUCT_VERSION = str(tomllib.load(version_file)["project"]["version"])

if not (WEB_DIST / "index.html").is_file():
    raise SystemExit("Build web/dist before running PyInstaller")

common_datas = [
    (str(WEB_DIST), "elsewise/web_dist"),
    (str(MIGRATIONS), "elsewise/migrations"),
    (str(ASSETS / "elsewise-logo-dark.png"), "elsewise/assets"),
    (str(ASSETS / "elsewise-logo-light.png"), "elsewise/assets"),
    (str(ASSETS / "white-bunny-avatar.png"), "elsewise/assets"),
    (str(ASSETS / "kofi-icon.png"), "elsewise/assets"),
    (str(ROOT / "shared" / "external-links.json"), "elsewise/assets"),
    (str(ROOT / "shared" / "theme-tokens.json"), "elsewise/assets"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
common_datas += collect_data_files("customtkinter")
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("elsewise.services")
    + ["PIL._tkinter_finder"]
)


def analysis(script):
    return Analysis(
        [str(script)],
        pathex=[str(ROOT / "server" / "src")],
        binaries=[],
        datas=common_datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=1,
    )


gui_analysis = analysis(ROOT / "server/src/elsewise/launcher/app.py")
cli_analysis = analysis(ROOT / "server/src/elsewise/cli.py")
server_analysis = analysis(ROOT / "server/src/elsewise/runtime/server_runner.py")

MERGE(
    (gui_analysis, "elsewise-gui", "elsewise-gui"),
    (cli_analysis, "elsewise", "elsewise"),
    (server_analysis, "elsewise-server", "elsewise-server"),
)

gui_icon = None
if sys.platform == "darwin":
    gui_icon = str(GENERATED / "elsewise.icns")
elif sys.platform == "win32":
    gui_icon = str(GENERATED / "elsewise.ico")


def executable(source, name, *, console):
    return EXE(
        PYZ(source.pure),
        source.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=gui_icon if name in {"Elsewise", "elsewise-gui"} else None,
    )


gui_exe = executable(gui_analysis, "elsewise-gui", console=False)
cli_exe = executable(cli_analysis, "elsewise", console=True)
server_exe = executable(server_analysis, "elsewise-server", console=False)

collection = COLLECT(
    gui_exe,
    cli_exe,
    server_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    cli_analysis.binaries,
    cli_analysis.datas,
    server_analysis.binaries,
    server_analysis.datas,
    strip=False,
    upx=False,
    name="Elsewise",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Elsewise.app",
        icon=str(GENERATED / "elsewise.icns"),
        bundle_identifier="so.elsewise.desktop",
        version=PRODUCT_VERSION,
        info_plist={
            "CFBundleDisplayName": "Elsewise",
            "CFBundleName": "Elsewise",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
        },
    )
