"""
Broadcasts JSON messages to every connected dashboard (multiple
browsers/phones can watch the same live session). Messages originate
on the MQTT thread (not the asyncio loop), so pushing into asyncio
land goes through call_soon_threadsafe — see mqtt_client.py.
"""
import asyncio
import json
from typing import Set
from fastapi import WebSocket


class WSManager:
    def __init__(self):
        self.clients: Set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def _broadcast(self, message: dict):
        if not self.clients:
            return
        payload = json.dumps(message)
        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def broadcast_threadsafe(self, message: dict):
        """Call this from the MQTT thread (not the asyncio loop)."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(message), self.loop)


ws_manager = WSManager()
