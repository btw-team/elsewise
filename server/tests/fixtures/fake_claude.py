#!/usr/bin/env python3
"""Small subprocess fixture that mimics the Claude Code JSONL interface."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def append_log(payload: dict[str, object]) -> None:
    path = os.environ.get("FAKE_CLAUDE_LOG")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def raise_system_exit() -> None:
    raise SystemExit(143)


if sys.argv[1:] == ["--version"]:
    print("2.1.999 (Claude Code)")
    raise SystemExit(0)

if sys.argv[1:] == ["auth", "status"]:
    mode = os.environ.get("FAKE_CLAUDE_AUTH", "ready")
    if mode == "missing":
        print("Not logged in", file=sys.stderr)
        raise SystemExit(1)
    if mode == "malformed":
        print("not-json")
        raise SystemExit(0)
    print(json.dumps({"loggedIn": True, "authMethod": "oauth"}))
    raise SystemExit(0)

prompt = sys.stdin.read()
append_log(
    {
        "argv": sys.argv[1:],
        "stdin": prompt,
        "cwd": os.getcwd(),
        "environment": {
            key: os.environ.get(key)
            for key in (
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
                "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS",
                "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
                "ENABLE_CLAUDEAI_MCP_SERVERS",
            )
        },
    }
)

mode = os.environ.get("FAKE_CLAUDE_MODE", "success")
if mode in {"hang", "timeout"}:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    append_log({"child_pid": child.pid, "parent_pid": os.getpid()})
    signal.signal(signal.SIGTERM, lambda *_: raise_system_exit())
    while True:
        time.sleep(1)

if mode == "malformed":
    print("not-json", flush=True)
    raise SystemExit(0)

if mode == "crash":
    print("synthetic Claude crash", file=sys.stderr, flush=True)
    raise SystemExit(7)

if mode == "noisy_stderr":
    # Exceed a typical subprocess pipe buffer before writing stdout. Providers
    # must keep draining stderr even after their retained diagnostic limit.
    sys.stderr.write("diagnostic noise\n" * 100_000)
    sys.stderr.flush()

if mode == "missing_session":
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "result": "Session not found on disk",
            }
        ),
        flush=True,
    )
    raise SystemExit(1)

print(
    json.dumps(
        {
            "type": "stream_event",
            "parent_tool_use_id": "subagent-1",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "ignored subagent"},
            },
        }
    ),
    flush=True,
)
print(
    json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hello "},
            },
        }
    ),
    flush=True,
)
print(
    json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        }
    ),
    flush=True,
)
print(
    json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "world"},
            },
        }
    ),
    flush=True,
)
print(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 12,
            "duration_api_ms": 10,
            "num_turns": 1,
            "total_cost_usd": 0.001,
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "result": "Hello world",
        }
    ),
    flush=True,
)
