import asyncio
import contextlib
import json
import time
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect

from elsewise.api.security import safe_ui_websocket
from elsewise.observability import RuntimeDiagnostics
from elsewise.services.runtime_status import RuntimeStatusService
from elsewise.settings.limits import UI_SEND_TIMEOUT_SECONDS


def _fingerprint(payload: dict[str, Any]) -> str:
    stable = dict(payload)
    server = dict(cast(dict[str, Any], stable["server"]))
    server.pop("uptime_seconds", None)
    stable["server"] = server
    return json.dumps(stable, sort_keys=True, separators=(",", ":"))


async def runtime_websocket(websocket: WebSocket) -> None:
    if not safe_ui_websocket(websocket):
        await websocket.close(code=1008, reason="invalid_origin")
        return
    await websocket.accept()
    diagnostics = cast(RuntimeDiagnostics, websocket.app.state.diagnostics)
    service = cast(RuntimeStatusService, websocket.app.state.runtime_status)
    diagnostics.connected("launcher")
    disconnect_task = asyncio.create_task(
        _wait_for_disconnect(websocket), name="elsewise-launcher-disconnect"
    )
    sequence = 0
    previous = ""
    last_sent = 0.0
    try:
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(disconnect_task), timeout=0.5)
                return
            except TimeoutError:
                pass
            payload = await service.snapshot()
            fingerprint = _fingerprint(payload)
            now = time.monotonic()
            if fingerprint == previous and now - last_sent < 30.0:
                continue
            sequence += 1
            await asyncio.wait_for(
                websocket.send_json(
                    {"type": "runtime.status", "sequence": sequence, "payload": payload}
                ),
                timeout=UI_SEND_TIMEOUT_SECONDS,
            )
            previous = fingerprint
            last_sent = now
    except (WebSocketDisconnect, TimeoutError):
        return
    finally:
        disconnect_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await disconnect_task
        diagnostics.disconnected("launcher")


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
