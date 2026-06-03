from typing import Dict
from fastapi import WebSocket
import asyncio
import json

class WebSocketManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}

    async def connect(self, crawl_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[crawl_id] = websocket

    def disconnect(self, crawl_id: str):
        self.connections.pop(crawl_id, None)

    async def send(self, crawl_id: str, message: dict):
        ws = self.connections.get(crawl_id)
        if ws:
            await ws.send_json(message)
