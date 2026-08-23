import asyncio
import contextlib
import json
import os
import re
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from elsewise import __version__
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


class AppServerError(RuntimeError):
    pass


class CodexAppServerProvider:
    def __init__(
        self,
        executable: str = "codex",
        *,
        startup_timeout: float = 15.0,
        shutdown_timeout: float = 3.0,
        stderr_limit: int = 32_768,
    ) -> None:
        self.executable = executable
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout
        self.stderr_limit = stderr_limit
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2048)
        self._write_lock = asyncio.Lock()
        self._stderr = ""
        self._health = AgentHealth("stopped")
        self._models: tuple[AgentModelOption, ...] | None = None

    async def health(self) -> AgentHealth:
        if self._process is not None and self._process.returncode is not None:
            return AgentHealth(
                "error", message=f"Codex app-server exited ({self._process.returncode})."
            )
        return self._health

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._models = None
        self._health = AgentHealth("starting")
        while not self._notifications.empty():
            self._notifications.get_nowait()
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "app-server",
                "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Keep terminal SIGINT scoped to Elsewise. The server owns the
                # Codex process tree and shuts it down in a controlled order.
                start_new_session=os.name == "posix",
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self._health = AgentHealth("unavailable", message=str(exc))
            raise AppServerError(f"Unable to start Codex CLI: {exc}") from exc
        self._process = process
        self._reader_task = asyncio.create_task(self._read_stdout(), name="codex-app-server-out")
        self._stderr_task = asyncio.create_task(self._read_stderr(), name="codex-app-server-err")
        try:
            initialized = await asyncio.wait_for(
                self._request(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "elsewise",
                            "title": "Elsewise",
                            "version": __version__,
                        }
                    },
                ),
                timeout=self.startup_timeout,
            )
            await self._notify("initialized")
            account = await asyncio.wait_for(
                self._request("account/read", {"refreshToken": False}),
                timeout=self.startup_timeout,
            )
        except Exception as exc:
            await self.stop()
            self._health = AgentHealth("error", message=str(exc))
            raise
        user_agent = initialized.get("userAgent")
        authenticated = account.get("account") is not None or not account.get(
            "requiresOpenaiAuth", True
        )
        self._health = AgentHealth(
            "ready" if authenticated else "unavailable",
            version=str(user_agent) if user_agent else None,
            authenticated=authenticated,
            message=None if authenticated else "Codex CLI is not authenticated.",
        )

    async def stop(self) -> None:
        process = self._process
        self._process = None
        reader_tasks = tuple(
            task for task in (self._reader_task, self._stderr_task) if task is not None
        )
        self._reader_task = None
        self._stderr_task = None
        if process is not None:
            if process.returncode is None and process.stdin is not None:
                process.stdin.close()
            if process.returncode is None and not await self._wait_for_exit(process):
                self._signal_process(process, signal.SIGTERM)
                if not await self._wait_for_exit(process):
                    self._signal_process(process, signal.SIGKILL)
                    # Never leave application shutdown behind an unbounded wait,
                    # even if an OS-level subprocess transport misbehaves.
                    await self._wait_for_exit(process)
            if os.name == "posix":
                # The direct process may exit while one of its workers remains in
                # the isolated process group and keeps stdio descriptors alive.
                self._signal_process(process, signal.SIGKILL, group_only=True)
        for task in reader_tasks:
            if task is not None and not task.done():
                task.cancel()
        if reader_tasks:
            done, _ = await asyncio.wait(reader_tasks, timeout=self.shutdown_timeout)
            for task in done:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    task.result()
        error = AppServerError("Codex app-server stopped.")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        self._models = None
        self._health = AgentHealth("stopped")

    async def models(self) -> tuple[AgentModelOption, ...]:
        self._require_ready()
        if self._models is not None:
            return self._models
        result = await asyncio.wait_for(
            self._request("model/list", {"limit": 100}), timeout=self.startup_timeout
        )
        parsed: list[AgentModelOption] = []
        for item in result.get("data", []):
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("model")
            if not isinstance(model_id, str) or not model_id:
                continue
            efforts = tuple(
                str(effort["reasoningEffort"])
                for effort in item.get("supportedReasoningEfforts", [])
                if isinstance(effort, dict) and effort.get("reasoningEffort")
            )
            default_effort = item.get("defaultReasoningEffort")
            parsed.append(
                AgentModelOption(
                    id=model_id,
                    name=str(item.get("displayName") or model_id),
                    description=str(item.get("description") or ""),
                    reasoning_efforts=efforts,
                    default_reasoning_effort=(
                        str(default_effort) if default_effort is not None else None
                    ),
                )
            )
        self._models = tuple(parsed)
        return self._models

    async def _wait_for_exit(self, process: asyncio.subprocess.Process) -> bool:
        try:
            await asyncio.wait_for(process.wait(), timeout=self.shutdown_timeout)
        except TimeoutError:
            return False
        return True

    @staticmethod
    def _signal_process(
        process: asyncio.subprocess.Process,
        requested_signal: signal.Signals,
        *,
        group_only: bool = False,
    ) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, requested_signal)
                return
            except ProcessLookupError:
                return
            except PermissionError:
                if group_only:
                    return
        if group_only or process.returncode is not None:
            return
        try:
            if requested_signal == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    async def create_thread(self, config: ThreadConfig) -> str:
        self._require_ready()
        result = await asyncio.wait_for(
            self._request(
                "thread/start",
                {
                    "cwd": config.cwd,
                    "model": config.model,
                    "config": (
                        {"model_reasoning_effort": config.reasoning_effort}
                        if config.reasoning_effort
                        else None
                    ),
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write"
                    if config.permissions.allow_workspace_write
                    else "read-only",
                    "ephemeral": False,
                },
            ),
            timeout=self.startup_timeout,
        )
        return str(result["thread"]["id"])

    async def resume_thread(self, thread_id: str, config: ThreadConfig) -> None:
        self._require_ready()
        await asyncio.wait_for(
            self._request(
                "thread/resume",
                {
                    "threadId": thread_id,
                    "cwd": config.cwd,
                    "model": config.model,
                    "config": (
                        {"model_reasoning_effort": config.reasoning_effort}
                        if config.reasoning_effort
                        else None
                    ),
                    "approvalPolicy": "never",
                    "sandbox": "workspace-write"
                    if config.permissions.allow_workspace_write
                    else "read-only",
                },
            ),
            timeout=self.startup_timeout,
        )

    async def run_turn(
        self, thread_id: str, input_text: str, config: RunConfig
    ) -> AsyncIterator[AgentEvent]:
        self._require_ready()
        response = await asyncio.wait_for(
            self._request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": input_text}],
                    "cwd": config.cwd,
                    "model": config.model,
                    "effort": config.reasoning_effort,
                    "approvalPolicy": "never",
                    "sandboxPolicy": config.permissions.sandbox_policy(config.cwd),
                },
            ),
            timeout=self.startup_timeout,
        )
        turn_id = str(response["turn"]["id"])
        yield AgentEvent("started", turn_id=turn_id)
        while True:
            try:
                notification = await asyncio.wait_for(
                    self._notification_for(thread_id, turn_id),
                    timeout=config.inactivity_timeout_seconds,
                )
            except TimeoutError:
                with contextlib.suppress(Exception):
                    await self.cancel_turn(thread_id, turn_id)
                yield AgentEvent(
                    "failed",
                    turn_id=turn_id,
                    error_type="inactivity_timeout",
                    error_message="Codex produced no activity before the inactivity timeout.",
                )
                return
            method = notification.get("method")
            params = cast(dict[str, Any], notification.get("params", {}))
            if method == "item/agentMessage/delta":
                yield AgentEvent("delta", turn_id=turn_id, text=str(params.get("delta", "")))
            elif method == "turn/completed":
                turn = cast(dict[str, Any], params.get("turn", {}))
                status = turn.get("status")
                if status == "completed":
                    yield AgentEvent("completed", turn_id=turn_id, metadata={"turn": turn})
                elif status == "interrupted":
                    yield AgentEvent("interrupted", turn_id=turn_id, metadata={"turn": turn})
                else:
                    error = cast(dict[str, Any], turn.get("error") or {})
                    yield AgentEvent(
                        "failed",
                        turn_id=turn_id,
                        error_type="codex_turn_failed",
                        error_message=str(error.get("message", "Codex turn failed.")),
                        metadata={"turn": turn},
                    )
                return
            elif method == "error":
                yield AgentEvent(
                    "failed",
                    turn_id=turn_id,
                    error_type="codex_error",
                    error_message=str(params.get("message", "Codex app-server error.")),
                )
                return
            elif method == "transport/closed":
                yield AgentEvent(
                    "failed",
                    turn_id=turn_id,
                    error_type="app_server_exited",
                    error_message=str(
                        params.get("message", "Codex app-server exited unexpectedly.")
                    ),
                )
                return

    async def cancel_turn(self, thread_id: str, turn_id: str) -> None:
        await asyncio.wait_for(
            self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}),
            timeout=self.startup_timeout,
        )

    @property
    def stderr_tail(self) -> str:
        return self._stderr

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write({"id": request_id, "method": method, "params": params})
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self._write(message)

    async def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise AppServerError("Codex app-server is not running.")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        async with self._write_lock:
            process.stdin.write(encoded)
            await process.stdin.drain()

    async def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                request_id = message.get("id")
                if request_id is not None and (future := self._pending.get(request_id)) is not None:
                    if "error" in message:
                        future.set_exception(AppServerError(str(message["error"])))
                    else:
                        future.set_result(cast(dict[str, Any], message.get("result", {})))
                elif "method" in message:
                    if "id" in message:
                        await self._write(
                            {
                                "id": message["id"],
                                "error": {
                                    "code": -32601,
                                    "message": "Elsewise rejects interactive server requests.",
                                },
                            }
                        )
                    elif not self._notifications.full():
                        self._notifications.put_nowait(cast(dict[str, Any], message))
        except asyncio.CancelledError:
            raise
        finally:
            if self._process is process:
                return_code = await process.wait()
                self._health = AgentHealth(
                    "error", message=f"Codex app-server exited ({return_code})."
                )
                error = AppServerError(f"Codex app-server exited ({return_code}).")
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                closed = {
                    "method": "transport/closed",
                    "params": {"message": str(error)},
                }
                if not self._notifications.full():
                    self._notifications.put_nowait(closed)

    async def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        while chunk := await process.stderr.read(4096):
            decoded = chunk.decode(errors="replace")
            decoded = _SECRET_PATTERN.sub(r"\1\2[REDACTED]", decoded)
            self._stderr = (self._stderr + decoded)[-self.stderr_limit :]

    async def _notification_for(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        while True:
            notification = await self._notifications.get()
            if notification.get("method") == "transport/closed":
                return notification
            params = cast(dict[str, Any], notification.get("params", {}))
            if params.get("threadId") == thread_id and (
                params.get("turnId") == turn_id
                or cast(dict[str, Any], params.get("turn", {})).get("id") == turn_id
            ):
                return notification

    def _require_ready(self) -> None:
        if self._health.status != "ready":
            raise AppServerError(self._health.message or "Codex app-server is not ready.")


def canonical_cwd(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=True))
