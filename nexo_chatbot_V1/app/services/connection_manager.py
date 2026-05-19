from fastapi import WebSocket
from starlette.websockets import WebSocketState
from app.utils.logger import logger

class ConnectionManager:
    """Tracks active WebSocket connections keyed by session_id."""

    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active[session_id] = websocket
        logger.info(f"WebSocket connected: session={session_id} total={len(self.active)}")

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)
        logger.info(f"WebSocket disconnected: session={session_id} remaining={len(self.active)}")

    async def send(self, session_id: str, payload: dict):
        ws = self.active.get(session_id)
        if ws and ws.application_state == WebSocketState.CONNECTED:
            await ws.send_json(payload)

    def is_connected(self, session_id: str) -> bool:
        return session_id in self.active

manager = ConnectionManager()
