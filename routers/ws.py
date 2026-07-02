from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import get_logger
import storage

router = APIRouter(tags=["websocket"])
log = get_logger("finance.ws")

ACTIVE_CONNECTIONS: set[WebSocket] = set()
MAX_WS_CONNECTIONS = 100


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await websocket.accept()
    if len(ACTIVE_CONNECTIONS) >= MAX_WS_CONNECTIONS:
        log.warning("ws rejected: connection cap %d reached", MAX_WS_CONNECTIONS)
        try:
            await websocket.send_text('{"error":"connection_cap_reached"}')
            await websocket.close(code=1008)
        except Exception:
            pass
        return
    ACTIVE_CONNECTIONS.add(websocket)
    log.info("ws connected, total=%d", len(ACTIVE_CONNECTIONS))
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # No client message in 30s; probe liveness. A dead/half-open
                # socket raises here and is cleaned up in finally.
                await websocket.send_text("ping")
                continue
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws error: %s", exc)
    finally:
        ACTIVE_CONNECTIONS.discard(websocket)
        log.info("ws disconnected, total=%d", len(ACTIVE_CONNECTIONS))


async def broadcast_alert(msg: dict) -> None:
    conns = list(ACTIVE_CONNECTIONS)
    if not conns:
        return
    import json as _json
    payload = _json.dumps(msg)
    dead: list[WebSocket] = []
    sent = 0
    for ws in conns:
        try:
            await ws.send_text(payload)
            sent += 1
        except Exception:
            dead.append(ws)
    for ws in dead:
        ACTIVE_CONNECTIONS.discard(ws)
    log.info("broadcast to %d ws clients (%d dead removed)", sent, len(dead))
