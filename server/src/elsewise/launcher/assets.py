from pathlib import Path


def asset_path(name: str) -> Path | None:
    packaged = Path(__file__).resolve().parents[1] / "assets" / name
    repository = Path(__file__).resolve().parents[4] / "web" / "src" / "assets" / name
    for candidate in (packaged, repository):
        if candidate.is_file():
            return candidate
    return None
