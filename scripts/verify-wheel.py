from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    wheels = sorted(Path("dist").glob("elsewise-*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        raise SystemExit("No Elsewise wheel found in dist/.")

    wheel = wheels[-1]
    required = {
        "elsewise/exports/__init__.py",
        "elsewise/exports/markdown.py",
        "elsewise/migrations/env.py",
        "elsewise/migrations/versions/0001_initial.py",
        "elsewise/web_dist/index.html",
    }
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = sorted(required - names)
        if missing:
            formatted = "\n".join(f"- {name}" for name in missing)
            raise SystemExit(f"Wheel {wheel} is missing required files:\n{formatted}")
        if not any(name.startswith("elsewise/web_dist/assets/") for name in names):
            raise SystemExit(f"Wheel {wheel} is missing compiled web assets.")

    print(f"Verified Python distribution: {wheel}")


if __name__ == "__main__":
    main()
