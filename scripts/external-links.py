#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "shared" / "external-links.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Read the canonical product link manifest")
    parser.add_argument("key", nargs="?", help="Print one named URL")
    args = parser.parse_args()
    links = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.key:
        try:
            print(links[args.key])
        except KeyError as error:
            raise SystemExit(f"Unknown external-link key: {args.key}") from error
    else:
        print(json.dumps(links, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
