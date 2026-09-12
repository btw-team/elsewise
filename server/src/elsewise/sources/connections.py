import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

SendJson = Callable[[dict[str, Any]], Awaitable[None]]
Close = Callable[[int, str], Awaitable[None]]


class BrowserConnectionRegistry:
    def __init__(self) -> None:
        self._senders: dict[str, SendJson] = {}
        self._closers: dict[str, Close] = {}
        self._connection_ids: dict[str, str] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    def register(self, client_id: str, sender: SendJson, closer: Close) -> str:
        connection_id = str(uuid4())
        self._senders[client_id] = sender
        self._closers[client_id] = closer
        self._connection_ids[client_id] = connection_id
        return connection_id

    def unregister(self, client_id: str, connection_id: str | None = None) -> bool:
        if connection_id is not None and self._connection_ids.get(client_id) != connection_id:
            return False
        self._senders.pop(client_id, None)
        self._closers.pop(client_id, None)
        self._connection_ids.pop(client_id, None)
        return True

    async def close_client(self, client_id: str, *, reason: str = "client_revoked") -> None:
        closer = self._closers.get(client_id)
        if closer is not None:
            await closer(1008, reason)
        self.unregister(client_id)

    async def command(
        self,
        client_id: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        sender = self._senders.get(client_id)
        if sender is None:
            return {"result": "failed", "error_code": "producer_disconnected"}
        command_id = str(uuid4())
        payload = {**payload, "command_id": command_id}
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[command_id] = future
        try:
            await sender(payload)
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError:
            return {"result": "failed", "error_code": "finalize_timeout"}
        except Exception:
            return {"result": "failed", "error_code": "producer_error"}
        finally:
            self._pending.pop(command_id, None)

    def acknowledge(self, command_id: str, payload: dict[str, Any]) -> None:
        future = self._pending.get(command_id)
        if future is not None and not future.done():
            future.set_result(payload)
