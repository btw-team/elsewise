import asyncio
from collections.abc import AsyncIterator

from elsewise.agents.interface import (
    AgentEvent,
    AgentHealth,
    AgentModelOption,
    PermissionConfig,
    RunConfig,
    ThreadConfig,
)


class FakeAgentProvider:
    def __init__(self, *, chunks: tuple[str, ...] = ("Готово",), delay: float = 0.0) -> None:
        self.chunks = chunks
        self.delay = delay
        self.started = False
        self.created_threads: list[ThreadConfig] = []
        self.resumed_threads: list[tuple[str, ThreadConfig]] = []
        self.turns: list[tuple[str, str, RunConfig]] = []
        self.cancelled: set[str] = set()
        self._next_thread = 1
        self._next_turn = 1

    async def health(self) -> AgentHealth:
        return AgentHealth("ready" if self.started else "stopped", version="fake")

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def models(self) -> tuple[AgentModelOption, ...]:
        return (
            AgentModelOption(
                id="fake-model",
                name="Fake model",
                reasoning_efforts=("low", "medium", "high"),
                default_reasoning_effort="medium",
            ),
        )

    async def create_thread(self, config: ThreadConfig) -> str:
        self.created_threads.append(config)
        thread_id = f"fake-thread-{self._next_thread}"
        self._next_thread += 1
        return thread_id

    async def resume_thread(self, thread_id: str, config: ThreadConfig) -> None:
        self.resumed_threads.append((thread_id, config))

    async def run_turn(
        self, thread_id: str, input_text: str, config: RunConfig
    ) -> AsyncIterator[AgentEvent]:
        self.turns.append((thread_id, input_text, config))
        turn_id = f"fake-turn-{self._next_turn}"
        self._next_turn += 1
        yield AgentEvent("started", turn_id=turn_id)
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            if turn_id in self.cancelled:
                yield AgentEvent("interrupted", turn_id=turn_id)
                return
            yield AgentEvent("delta", turn_id=turn_id, text=chunk)
        yield AgentEvent("completed", turn_id=turn_id)

    async def cancel_turn(self, thread_id: str, turn_id: str) -> None:
        _ = thread_id
        self.cancelled.add(turn_id)


def fake_permissions() -> PermissionConfig:
    return PermissionConfig()
