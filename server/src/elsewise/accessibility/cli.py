import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import asdict

from elsewise.accessibility.backends import accessibility_backend
from elsewise.accessibility.explorer import sanitized_node


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elsewise-a11y-dump")
    parser.add_argument("--list", action="store_true", help="list candidate processes")
    parser.add_argument("--pid", type=int, help="inspect one process")
    parser.add_argument("--watch", action="store_true", help="poll a bounded sequence of snapshots")
    parser.add_argument("--watch-count", type=int, default=10, choices=range(1, 101))
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-depth", type=int, default=8, choices=range(1, 33))
    parser.add_argument("--max-nodes", type=int, default=2_000, choices=range(1, 10_001))
    parser.add_argument(
        "--show-text",
        action="store_true",
        help="include bounded accessible text; may contain private data",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend = accessibility_backend()
    health = backend.health()
    if args.list:
        print(
            json.dumps(
                {
                    "health": asdict(health),
                    "processes": [asdict(item) for item in backend.processes()],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.pid is None:
        build_parser().error("--pid is required unless --list is used")
    if health.status != "available":
        print(json.dumps({"health": asdict(health)}, ensure_ascii=False, indent=2))
        return 2
    count = args.watch_count if args.watch else 1
    for index in range(count):
        snapshot = backend.snapshot(
            args.pid,
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
        )
        print(
            json.dumps(
                {
                    "sequence": index + 1,
                    "backend": backend.id,
                    "pid": args.pid,
                    "tree": sanitized_node(snapshot, show_text=args.show_text),
                },
                ensure_ascii=False,
            )
        )
        if index + 1 < count:
            time.sleep(max(0.1, min(args.interval, 60.0)))
    return 0


def main() -> None:
    raise SystemExit(run())
