from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import get_logger
import storage

router = APIRouter(tags=["websocket"])
log = get_logger("finance.ws")

ACTIVE_CONNECTIONS: set[WebSocket] = set()


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await websocket.accept()
    ACTIVE_CONNECTIONS.add(websocket)
    log.info("ws connected, total=%d", len(ACTIVE_CONNECTIONS))
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        ACTIVE_CONNECTIONS.discard(websocket)
        log.info("ws disconnected, total=%d", len(ACTIVE_CONNECTIONS))


async def broadcast_alert(msg: dict) -> None:
    if not ACTIVE_CONNECTIONS:
        return
    import json as _json
    payload = _json.dumps(msg)
    dead: list[WebSocket] = []
    for ws in ACTIVE_CONNECTIONS:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ACTIVE_CONNECTIONS.discard(ws)
    log.info("broadcast to %d ws clients", len(ACTIVE_CONNECTIONS) - len(dead))
