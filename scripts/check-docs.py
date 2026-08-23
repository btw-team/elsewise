#!/usr/bin/env python3
"""Check local Markdown links, anchors, and images without requesting the network."""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_LINK = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
FENCED_BLOCK = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "data:")


def github_slug(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"[ -]+", "-", value).strip("-")


def anchors(path: Path) -> set[str]:
    text = FENCED_BLOCK.sub("", path.read_text(encoding="utf-8"))
    result: set[str] = set()
    occurrences: dict[str, int] = {}
    for heading in HEADING.findall(text):
        base = github_slug(heading)
        count = occurrences.get(base, 0)
        occurrences[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def markdown_files(root: Path) -> list[Path]:
    candidates = [root / "README.md", root / "CONTRIBUTING.md"]
    candidates.extend((root / "docs").rglob("*.md"))
    return sorted(path for path in candidates if path.is_file())


def link_targets(path: Path) -> list[str]:
    text = FENCED_BLOCK.sub("", path.read_text(encoding="utf-8"))
    targets = MARKDOWN_LINK.findall(text) + HTML_LINK.findall(text)
    return [target.strip().strip("<>").split(maxsplit=1)[0] for target in targets]


def check(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in markdown_files(root):
        for raw_target in link_targets(source):
            if not raw_target or raw_target.startswith(EXTERNAL_SCHEMES):
                continue
            relative, _, fragment = raw_target.partition("#")
            relative = unquote(relative.split("?", 1)[0])
            target = (source.parent / relative).resolve() if relative else source.resolve()
            try:
                target.relative_to(root)
            except ValueError:
                errors.append(f"{source.relative_to(root)}: link escapes repository: {raw_target}")
                continue
            if not target.exists():
                errors.append(f"{source.relative_to(root)}: missing target: {raw_target}")
                continue
            if fragment and target.is_file() and target.suffix.lower() == ".md":
                available = anchor_cache.setdefault(target, anchors(target))
                expected = github_slug(unquote(fragment))
                if expected not in available:
                    errors.append(f"{source.relative_to(root)}: missing anchor: {raw_target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    errors = check(arguments.root)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Documentation links are valid ({len(markdown_files(arguments.root))} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
