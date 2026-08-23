import asyncio
import contextlib
import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import pytest
from elsewise.agents.claude_cli import ClaudeCliError, ClaudeCodeProvider
from elsewise.agents.interface import AgentEvent, PermissionConfig, RunConfig, ThreadConfig


def fake_claude() -> Path:
    return Path(__file__).parent / "fixtures" / "fake_claude.py"


async def collect_turn(
    provider: ClaudeCodeProvider,
    thread_id: str,
    prompt: str,
    config: RunConfig,
) -> list[AgentEvent]:
    return [event async for event in provider.run_turn(thread_id, prompt, config)]


def read_log(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_claude_health_distinguishes_ready_auth_and_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1)
    await provider.start()
    health = await provider.health()
    assert (health.status, health.version, health.authenticated) == (
        "ready",
        "2.1.999 (Claude Code)",
        True,
    )

    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "missing")
    unauthenticated = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1)
    with pytest.raises(ClaudeCliError, match="Not logged in"):
        await unauthenticated.start()
    health = await unauthenticated.health()
    assert health.status == "unavailable"
    assert health.authenticated is False

    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "malformed")
    malformed = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1)
    with pytest.raises(ClaudeCliError, match="invalid JSON"):
        await malformed.start()
    assert (await malformed.health()).status == "error"

    unavailable = ClaudeCodeProvider("/definitely/missing/claude", startup_timeout=0.1)
    with pytest.raises(ClaudeCliError, match="Unable to start"):
        await unavailable.start()
    assert (await unavailable.health()).status == "unavailable"


@pytest.mark.asyncio
async def test_claude_first_turn_resume_streaming_metadata_and_stdin_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "claude.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    provider = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1)
    await provider.start()
    thread_id = await provider.create_thread(ThreadConfig(cwd=str(tmp_path)))
    prompt = "secret prompt that must only be sent over stdin"

    first = await collect_turn(
        provider,
        thread_id,
        prompt,
        RunConfig(
            cwd=str(tmp_path),
            model="sonnet",
            reasoning_effort="high",
            inactivity_timeout_seconds=1,
        ),
    )
    second = await collect_turn(
        provider,
        thread_id,
        "follow up",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=1),
    )

    assert [event.kind for event in first] == ["started", "delta", "delta", "completed"]
    assert "".join(event.text for event in first if event.kind == "delta") == "Hello world"
    assert first[-1].metadata == {
        "duration_ms": 12,
        "duration_api_ms": 10,
        "num_turns": 1,
        "total_cost_usd": 0.001,
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    assert "".join(event.text for event in second if event.kind == "delta") == "Hello world"

    calls = read_log(log_path)
    first_argv = calls[0]["argv"]
    second_argv = calls[1]["argv"]
    assert isinstance(first_argv, list) and isinstance(second_argv, list)
    assert calls[0]["stdin"] == prompt
    assert prompt not in first_argv
    assert ["--session-id", thread_id] == first_argv[-2:]
    assert ["--resume", thread_id] == second_argv[-2:]
    assert "--bare" in first_argv
    assert "--disable-slash-commands" in first_argv
    assert "--strict-mcp-config" in first_argv
    assert first_argv[first_argv.index("--model") + 1] == "sonnet"
    assert first_argv[first_argv.index("--effort") + 1] == "high"
    assert calls[0]["environment"] == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    }


@pytest.mark.asyncio
async def test_claude_restored_session_uses_resume_and_missing_session_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "resume.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    provider = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1)
    await provider.start()
    thread_id = "550e8400-e29b-41d4-a716-446655440000"
    await provider.resume_thread(thread_id, ThreadConfig(cwd=str(tmp_path)))
    events = await collect_turn(
        provider,
        thread_id,
        "restored",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=1),
    )
    assert events[-1].kind == "completed"
    assert read_log(log_path)[0]["argv"][-2:] == ["--resume", thread_id]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "missing_session")
    missing = await collect_turn(
        provider,
        thread_id,
        "must not create a replacement",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=1),
    )
    assert missing[-1].kind == "failed"
    assert missing[-1].error_type == "claude_session_missing"
    assert read_log(log_path)[-1]["argv"][-2:] == ["--resume", thread_id]


@pytest.mark.parametrize(
    (
        "allow_write",
        "allow_network",
        "expected_tools",
        "expected_allowed",
        "expected_denied",
    ),
    [
        (
            False,
            False,
            "Read,Glob,Grep,Bash",
            "Read,Glob,Grep,Bash",
            "Edit,Write,NotebookEdit,WebFetch,WebSearch,mcp__*",
        ),
        (
            False,
            True,
            "Read,Glob,Grep,Bash,WebFetch,WebSearch",
            "Read,Glob,Grep,Bash,WebFetch,WebSearch",
            "Edit,Write,NotebookEdit,mcp__*",
        ),
        (
            True,
            False,
            "Read,Glob,Grep,Bash,Edit,Write,NotebookEdit",
            "Read,Glob,Grep,Bash,Edit(/**),Write(/**),NotebookEdit(/**)",
            "WebFetch,WebSearch,mcp__*",
        ),
        (
            True,
            True,
            "Read,Glob,Grep,Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
            "Read,Glob,Grep,Bash,Edit(/**),Write(/**),NotebookEdit(/**),WebFetch,WebSearch",
            "mcp__*",
        ),
    ],
)
def test_claude_permissions_generate_exact_tools_and_sandbox(
    tmp_path: Path,
    allow_write: bool,
    allow_network: bool,
    expected_tools: str,
    expected_allowed: str,
    expected_denied: str,
) -> None:
    provider = ClaudeCodeProvider(str(fake_claude()))
    config = RunConfig(
        cwd=str(tmp_path),
        permissions=PermissionConfig(allow_write, allow_network),
    )
    command = provider._turn_command(
        "550e8400-e29b-41d4-a716-446655440000", is_new=True, config=config
    )

    assert command[command.index("--tools") + 1] == expected_tools
    assert command[command.index("--allowedTools") + 1] == expected_allowed
    assert command[command.index("--disallowedTools") + 1] == expected_denied
    settings = json.loads(command[command.index("--settings") + 1])
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    assert settings["sandbox"]["network"]["allowedDomains"] == (["*"] if allow_network else [])
    if allow_write:
        assert settings["sandbox"]["filesystem"] == {"allowWrite": [str(tmp_path)]}
    else:
        assert settings["sandbox"]["filesystem"] == {"denyWrite": ["/"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "error_type"),
    [
        ("malformed", "claude_protocol_error"),
        ("crash", "claude_turn_failed"),
        ("timeout", "inactivity_timeout"),
    ],
)
async def test_claude_malformed_crash_and_timeout_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    error_type: str,
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    provider = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1, shutdown_timeout=0.05)
    await provider.start()
    thread_id = await provider.create_thread(ThreadConfig(cwd=str(tmp_path)))
    timeout_seconds = 0.05 if mode == "timeout" else 1
    events = await collect_turn(
        provider,
        thread_id,
        "test",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=timeout_seconds),
    )
    assert events[-1].kind == "failed"
    assert events[-1].error_type == error_type
    await provider.stop()


@pytest.mark.asyncio
async def test_claude_drains_stderr_beyond_diagnostic_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "noisy_stderr")
    provider = ClaudeCodeProvider(
        str(fake_claude()),
        startup_timeout=1,
        shutdown_timeout=0.05,
        stderr_limit=1024,
    )
    await provider.start()
    thread_id = await provider.create_thread(ThreadConfig(cwd=str(tmp_path)))

    events = await collect_turn(
        provider,
        thread_id,
        "test",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=2),
    )

    assert events[-1].kind == "completed"
    await provider.stop()


@pytest.mark.asyncio
async def test_claude_cancel_and_shutdown_terminate_process_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "cancel.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_path))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    provider = ClaudeCodeProvider(str(fake_claude()), startup_timeout=1, shutdown_timeout=0.05)
    await provider.start()
    thread_id = await provider.create_thread(ThreadConfig(cwd=str(tmp_path)))
    stream = cast(
        AsyncGenerator[AgentEvent],
        provider.run_turn(
            thread_id,
            "cancel me",
            RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=5),
        ),
    )
    started = await anext(stream)
    assert started.kind == "started" and started.turn_id is not None
    waiting_for_output: asyncio.Future[AgentEvent] = asyncio.ensure_future(anext(stream))
    for _ in range(500):
        if log_path.exists() and any("child_pid" in item for item in read_log(log_path)):
            break
        await asyncio.sleep(0.01)
    process_entry = next(item for item in read_log(log_path) if "child_pid" in item)
    child_pid = int(process_entry["child_pid"])
    parent_pid = int(process_entry["parent_pid"])

    await provider.cancel_turn(thread_id, started.turn_id)
    with contextlib.suppress(StopAsyncIteration):
        await waiting_for_output
    await stream.aclose()
    await provider.stop()
    await asyncio.sleep(0.05)
    assert not Path(f"/proc/{parent_pid}").exists()
    assert not Path(f"/proc/{child_pid}").exists()
    assert (await provider.health()).status == "stopped"


@pytest.mark.skipif(
    os.environ.get("ELSEWISE_RUN_CLAUDE_LIVE") != "1",
    reason="Set ELSEWISE_RUN_CLAUDE_LIVE=1 to use the installed Claude Code CLI.",
)
@pytest.mark.asyncio
async def test_claude_live_initial_followup_shutdown_and_resume(tmp_path: Path) -> None:
    executable = os.environ.get("ELSEWISE_CLAUDE_EXECUTABLE", "claude")
    provider = ClaudeCodeProvider(executable, startup_timeout=10, shutdown_timeout=2)
    await provider.start()
    thread_id = await provider.create_thread(ThreadConfig(cwd=str(tmp_path)))
    first = await collect_turn(
        provider,
        thread_id,
        "Reply with exactly: first",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=120),
    )
    assert first[-1].kind == "completed"
    second = await collect_turn(
        provider,
        thread_id,
        "Reply with exactly: second",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=120),
    )
    assert second[-1].kind == "completed"
    await provider.stop()

    restored = ClaudeCodeProvider(executable, startup_timeout=10, shutdown_timeout=2)
    await restored.start()
    await restored.resume_thread(thread_id, ThreadConfig(cwd=str(tmp_path)))
    resumed = await collect_turn(
        restored,
        thread_id,
        "Reply with exactly: resumed",
        RunConfig(cwd=str(tmp_path), inactivity_timeout_seconds=120),
    )
    assert resumed[-1].kind == "completed"
    await restored.stop()
