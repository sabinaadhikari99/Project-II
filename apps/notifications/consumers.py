import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            logger.warning("WebSocket connection rejected: unauthenticated")
            await self.close(code=4001)
            return
        self.group_name = f"notifications_{self.user.id}"
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            logger.info("WebSocket connected: user=%s group=%s", self.user.id, self.group_name)
        except Exception as e:
            logger.error("WebSocket connect error for user %s: %s", self.user.id, e)
            await self.close(code=1011)

    async def disconnect(self, close_code):
        if hasattr(self, "group_name") and self.group_name:
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
                logger.debug("WebSocket disconnected: group=%s code=%s", self.group_name, close_code)
            except Exception as e:
                logger.warning("WebSocket disconnect cleanup error: %s", e)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get("action")
            if action == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))
        except json.JSONDecodeError:
            logger.debug("WebSocket received invalid JSON")

    async def notification_message(self, event):
        try:
            await self.send(text_data=json.dumps(event["data"]))
        except Exception as e:
            logger.error("WebSocket send error for user %s: %s", self.user.id, e)
