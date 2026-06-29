import logging
import os
from telethon import TelegramClient

logger = logging.getLogger(__name__)


class TelethonClientManager:
    """Manager for Telethon client instances."""

    def __init__(self):
        self.clients = {}
        self.api_id = int(os.getenv("TELETHON_API_ID", "0"))
        self.api_hash = os.getenv("TELETHON_API_HASH", "")

    async def get_client(self, session_name: str) -> TelegramClient:
        """Get or create a Telethon client for a session."""
        if session_name not in self.clients:
            session_path = f"sessions/{session_name}"
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()
            self.clients[session_name] = client
            logger.info(f"Connected Telethon client: {session_name}")

        return self.clients[session_name]

    async def disconnect_client(self, session_name: str):
        """Disconnect a Telethon client."""
        if session_name in self.clients:
            client = self.clients[session_name]
            await client.disconnect()
            del self.clients[session_name]
            logger.info(f"Disconnected Telethon client: {session_name}")

    async def disconnect_all(self):
        """Disconnect all clients."""
        for session_name in list(self.clients.keys()):
            await self.disconnect_client(session_name)

    async def send_message(self, session_name: str, chat_id: str, message: str) -> bool:
        """Send a message to a chat. Returns True if successful."""
        try:
            client = await self.get_client(session_name)
            await client.send_message(chat_id, message)
            logger.info(f"Message sent to {chat_id} via {session_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return False
