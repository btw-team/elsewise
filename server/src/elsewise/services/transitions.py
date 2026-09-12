import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from elsewise.services.errors import ServiceError

T = TypeVar("T")


class TransitionExecutor:
    """Serializes lifecycle transitions and rejects unbounded queue growth."""

    def __init__(self, *, capacity: int = 128) -> None:
        self._lock = asyncio.Lock()
        self._capacity = capacity
        self._waiting = 0

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        if self._waiting >= self._capacity:
            raise ServiceError(
                "transition_queue_full",
                "The transition queue is full.",
                status_code=429,
            )
        self._waiting += 1
        try:
            async with self._lock:
                return await operation()
        finally:
            self._waiting -= 1
