#!/usr/bin/env python3
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web/src/assets/elsewise-logo.png"
OUTPUT = ROOT / "packaging/generated"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as image:
        prepared = image.convert("RGBA")
        prepared.save(
            OUTPUT / "elsewise.ico",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        prepared.save(
            OUTPUT / "elsewise.icns",
            append_images=[prepared],
            sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512)],
        )
        prepared.resize((256, 256), Image.Resampling.LANCZOS).save(OUTPUT / "elsewise.png")


if __name__ == "__main__":
    main()
