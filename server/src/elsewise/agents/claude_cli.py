import asyncio
import contextlib
import json
import os
import re
import signal
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from elsewise.agents.interface import (
    AgentEvent,
    AgentHealth,
    AgentModelOption,
    RunConfig,
    ThreadConfig,
)

_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token)([\"'=:\s]+)([^\s\",}]+)"
)


class ClaudeCliError(RuntimeError):
    pass


class ClaudeAuthError(ClaudeCliError):
    pass


class ClaudeProtocolError(ClaudeCliError):
    pass


class ClaudeCodeProvider:
    def __init__(
        self,
        executable: str = "claude",
        *,
        startup_timeout: float = 15.0,
        shutdown_timeout: float = 3.0,
        stderr_limit: int = 32_768,
    ) -> None:
        self.executable = executable
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout
        self.stderr_limit = stderr_limit
        self._health = AgentHealth("stopped")
        self._new_threads: set[str] = set()
        self._active: dict[str, asyncio.subprocess.Process] = {}
        self._active_lock = asyncio.Lock()

    async def health(self) -> AgentHealth:
        return self._health

    async def start(self) -> None:
        self._health = AgentHealth("starting")
        try:
            version_output = await self._probe("--version")
            try:
                auth_output = await self._probe("auth", "status")
            except ClaudeProtocolError:
                raise
            except ClaudeCliError as exc:
                raise ClaudeAuthError(str(exc)) from exc
            try:
                auth_status = json.loads(auth_output)
                if not isinstance(auth_status, dict):
                    raise ValueError("Authentication status must be a JSON object.")
            except (json.JSONDecodeError, ValueError) as exc:
                raise ClaudeProtocolError("Claude auth status returned invalid JSON.") from exc
        except FileNotFoundError as exc:
            self._health = AgentHealth("unavailable", message=str(exc))
            raise ClaudeCliError(f"Unable to start Claude Code CLI: {exc}") from exc
        except PermissionError as exc:
            self._health = AgentHealth("unavailable", message=str(exc))
            raise ClaudeCliError(f"Unable to start Claude Code CLI: {exc}") from exc
        except ClaudeAuthError as exc:
            self._health = AgentHealth("unavailable", authenticated=False, message=str(exc))
            raise
        except ClaudeCliError as exc:
            self._health = AgentHealth("error", message=str(exc))
            raise
        version = version_output.strip().splitlines()[0] if version_output.strip() else None
        self._health = AgentHealth("ready", version=version, authenticated=True)

    async def stop(self) -> None:
        async with self._active_lock:
            processes = tuple(self._active.values())
            self._active.clear()
        await asyncio.gather(
            *(self._stop_process(process) for process in processes),
            return_exceptions=True,
        )
        self._health = AgentHealth("stopped")

    async def models(self) -> tuple[AgentModelOption, ...]:
        return (
            AgentModelOption(
                id="default",
                name="Claude Code default",
                reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
                default_reasoning_effort=None,
            ),
            AgentModelOption(
                id="sonnet",
                name="Sonnet",
                reasoning_efforts=("low", "medium", "high", "max"),
                default_reasoning_effort="high",
            ),
            AgentModelOption(
                id="opus",
                name="Opus",
                reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
                default_reasoning_effort="xhigh",
            ),
            AgentModelOption(id="haiku", name="Haiku"),
        )

    async def create_thread(self, config: ThreadConfig) -> str:
        _ = config
        self._require_ready()
        thread_id = str(uuid4())
        self._new_threads.add(thread_id)
        return thread_id

    async def resume_thread(self, thread_id: str, config: ThreadConfig) -> None:
        _ = config
        self._require_ready()
        self._new_threads.discard(thread_id)

    async def run_turn(
        self, thread_id: str, input_text: str, config: RunConfig
    ) -> AsyncIterator[AgentEvent]:
        self._require_ready()
        is_new = thread_id in self._new_threads
        turn_id = str(uuid4())
        command = self._turn_command(thread_id, is_new=is_new, config=config)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=config.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._turn_environment(),
                start_new_session=os.name == "posix",
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            yield AgentEvent(
                "failed",
                turn_id=turn_id,
                error_type="claude_unavailable",
                error_message=str(exc),
            )
            return

        async with self._active_lock:
            self._active[turn_id] = process
        stderr_task = asyncio.create_task(self._read_stderr(process))
        yield AgentEvent("started", turn_id=turn_id)
        saw_result = False
        try:
            assert process.stdin is not None
            process.stdin.write(input_text.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            assert process.stdout is not None
            while True:
                try:
                    raw_line = await asyncio.wait_for(
                        process.stdout.readline(), timeout=config.inactivity_timeout_seconds
                    )
                except TimeoutError:
                    await self._stop_process(process)
                    yield AgentEvent(
                        "failed",
                        turn_id=turn_id,
                        error_type="inactivity_timeout",
                        error_message=(
                            "Claude Code produced no activity before the inactivity timeout."
                        ),
                    )
                    return
                if not raw_line:
                    break
                try:
                    message = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._stop_process(process)
                    yield AgentEvent(
                        "failed",
                        turn_id=turn_id,
                        error_type="claude_protocol_error",
                        error_message="Claude Code emitted invalid stream JSON.",
                    )
                    return
                if (
                    message.get("type") == "stream_event"
                    and message.get("parent_tool_use_id") is None
                ):
                    event = message.get("event")
                    if not isinstance(event, dict) or event.get("type") != "content_block_delta":
                        continue
                    delta = event.get("delta")
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if isinstance(text, str) and text:
                            yield AgentEvent("delta", turn_id=turn_id, text=text)
                elif message.get("type") == "result":
                    saw_result = True
                    subtype = str(message.get("subtype", ""))
                    if subtype == "success" and not bool(message.get("is_error")):
                        self._new_threads.discard(thread_id)
                        metadata = {
                            key: message[key]
                            for key in (
                                "duration_ms",
                                "duration_api_ms",
                                "num_turns",
                                "total_cost_usd",
                                "usage",
                            )
                            if key in message
                        }
                        yield AgentEvent("completed", turn_id=turn_id, metadata=metadata)
                    else:
                        error_message = str(
                            message.get("result") or message.get("error") or "Claude turn failed."
                        )
                        yield AgentEvent(
                            "failed",
                            turn_id=turn_id,
                            error_type=self._error_type(error_message),
                            error_message=self._redact(error_message),
                        )
                    if not await self._wait_for_exit(process):
                        await self._stop_process(process)
                    return
            return_code = await process.wait()
            stderr = await stderr_task
            if not saw_result:
                yield AgentEvent(
                    "failed",
                    turn_id=turn_id,
                    error_type=self._error_type(stderr),
                    error_message=self._redact(
                        stderr or f"Claude Code exited ({return_code}) without a result."
                    ),
                )
        except asyncio.CancelledError:
            await self._stop_process(process)
            raise
        finally:
            async with self._active_lock:
                self._active.pop(turn_id, None)
            if not stderr_task.done():
                stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stderr_task

    async def cancel_turn(self, thread_id: str, turn_id: str) -> None:
        _ = thread_id
        async with self._active_lock:
            process = self._active.get(turn_id)
        if process is not None:
            await self._stop_process(process)

    async def _probe(self, *arguments: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                *arguments,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except (FileNotFoundError, PermissionError):
            raise
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.startup_timeout
            )
        except TimeoutError as exc:
            await self._stop_process(process)
            raise ClaudeCliError("Claude Code health check timed out.") from exc
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise ClaudeCliError(self._redact(message or "Claude Code is not authenticated."))
        try:
            return stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ClaudeProtocolError("Claude Code health check returned invalid UTF-8.") from exc

    def _turn_command(self, thread_id: str, *, is_new: bool, config: RunConfig) -> list[str]:
        settings = self._sandbox_settings(config)
        tools = ["Read", "Glob", "Grep", "Bash"]
        allowed = list(tools)
        denied: list[str] = []
        if config.permissions.allow_workspace_write:
            tools.extend(("Edit", "Write", "NotebookEdit"))
            allowed.extend(("Edit(/**)", "Write(/**)", "NotebookEdit(/**)"))
        else:
            denied.extend(("Edit", "Write", "NotebookEdit"))
        if config.permissions.allow_network:
            tools.extend(("WebFetch", "WebSearch"))
            allowed.extend(("WebFetch", "WebSearch"))
        else:
            denied.extend(("WebFetch", "WebSearch"))
        command = [
            self.executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--bare",
            "--disable-slash-commands",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--no-chrome",
            "--permission-mode",
            "dontAsk",
            "--tools",
            ",".join(tools),
            "--allowedTools",
            ",".join(allowed),
            "--settings",
            json.dumps(settings, separators=(",", ":")),
        ]
        command.extend(("--disallowedTools", ",".join((*denied, "mcp__*"))))
        if config.model:
            command.extend(("--model", config.model))
        if config.reasoning_effort:
            command.extend(("--effort", config.reasoning_effort))
        command.extend(("--session-id" if is_new else "--resume", thread_id))
        return command

    @staticmethod
    def _turn_environment() -> dict[str, str]:
        environment = dict(os.environ)
        environment.pop("CLAUDECODE", None)
        environment.pop("CLAUDE_CODE_CHILD_SESSION", None)
        environment.update(
            {
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
                "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_FORCE_SESSION_PERSISTENCE": "1",
                "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            }
        )
        return environment

    @staticmethod
    def _sandbox_settings(config: RunConfig) -> dict[str, Any]:
        sandbox: dict[str, Any] = {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "network": {
                "allowedDomains": ["*"] if config.permissions.allow_network else [],
            },
        }
        if config.permissions.allow_workspace_write:
            sandbox["filesystem"] = {"allowWrite": [config.cwd]}
        else:
            sandbox["filesystem"] = {"denyWrite": ["/"]}
        return {"sandbox": sandbox, "autoMemoryEnabled": False}

    async def _read_stderr(self, process: asyncio.subprocess.Process) -> str:
        assert process.stderr is not None
        retained = bytearray()
        while chunk := await process.stderr.read(8192):
            retained.extend(chunk)
            if len(retained) > self.stderr_limit:
                del retained[: len(retained) - self.stderr_limit]
        return retained.decode("utf-8", errors="replace").strip()

    async def _stop_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
        if await self._wait_for_exit(process):
            return
        self._signal(process, signal.SIGTERM)
        if await self._wait_for_exit(process):
            return
        self._signal(process, signal.SIGKILL)
        await self._wait_for_exit(process)

    async def _wait_for_exit(self, process: asyncio.subprocess.Process) -> bool:
        try:
            await asyncio.wait_for(process.wait(), timeout=self.shutdown_timeout)
        except TimeoutError:
            return False
        return True

    @staticmethod
    def _signal(process: asyncio.subprocess.Process, requested: signal.Signals) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, requested)
            elif requested == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    def _require_ready(self) -> None:
        if self._health.status != "ready":
            raise ClaudeCliError(self._health.message or "Claude Code CLI is not ready.")

    @staticmethod
    def _error_type(message: str) -> str:
        lowered = message.lower()
        if "session" in lowered and any(word in lowered for word in ("not found", "missing")):
            return "claude_session_missing"
        return "claude_turn_failed"

    @staticmethod
    def _redact(message: str) -> str:
        return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", message)[:20_000]
