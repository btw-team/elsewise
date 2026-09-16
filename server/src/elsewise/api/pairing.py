import asyncio
import json
from typing import cast

from fastapi import WebSocket, WebSocketDisconnect

from elsewise.api.security import safe_extension_origin
from elsewise.protocol.models import PROTOCOL_VERSION, PairingCancel, PairingRequest
from elsewise.services.errors import ServiceError
from elsewise.services.pairing import PairingService


async def pairing_websocket(websocket: WebSocket) -> None:
    if not safe_extension_origin(websocket.headers.get("origin", "")):
        await websocket.close(code=1008, reason="invalid_origin")
        return
    await websocket.accept()
    pairing = cast(PairingService, websocket.app.state.pairing)
    request_id: str | None = None
    nonce = ""
    try:
        raw = await websocket.receive_text()
        try:
            payload = json.loads(raw)
            message = PairingRequest.model_validate(payload)
        except (json.JSONDecodeError, ValueError):
            await websocket.send_json(
                {
                    "type": "pairing.error",
                    "protocol_version": PROTOCOL_VERSION,
                    "code": "invalid_message",
                }
            )
            await websocket.close(code=1008)
            return
        nonce = message.nonce
        request = pairing.create_request(
            installation_id=str(message.installation_id),
            browser_family=message.browser_family,
            display_name=message.display_name,
            extension_version=message.extension_version,
            nonce=nonce,
        )
        request_id = request.id
        await websocket.send_json(
            {
                "type": "pairing.pending",
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request.id,
                "expires_at": request.expires_at.isoformat(),
            }
        )
        while True:
            delivery = pairing.take_delivery(request.id, nonce)
            if delivery is not None:
                await websocket.send_json(
                    {
                        "type": "pairing.approved",
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request.id,
                        "client_id": delivery.client_id,
                        "credential": delivery.credential,
                    }
                )
                return
            state = pairing.request_state(request.id, nonce)
            if state != "pending":
                await websocket.send_json(
                    {
                        "type": f"pairing.{state}",
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request.id,
                    }
                )
                return
            try:
                PairingCancel.model_validate_json(
                    await asyncio.wait_for(websocket.receive_text(), 0.2)
                )
            except TimeoutError:
                continue
            except ValueError:
                await websocket.send_json(
                    {
                        "type": "pairing.error",
                        "protocol_version": PROTOCOL_VERSION,
                        "code": "invalid_message",
                    }
                )
                continue
            pairing.decide(request.id, "cancelled")
            await websocket.send_json(
                {
                    "type": "pairing.cancelled",
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": request.id,
                }
            )
            return
    except WebSocketDisconnect:
        return
    except ServiceError as exc:
        await websocket.send_json(
            {"type": "pairing.error", "protocol_version": PROTOCOL_VERSION, "code": exc.code}
        )
    finally:
        # Disconnect does not cancel the request: the same nonce may reconnect
        # before expiry and receive the one-time delivery.
        _ = request_id
