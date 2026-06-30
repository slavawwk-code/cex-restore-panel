import logging

from telethon import TelegramClient

from app.database.models import AdvertisingAccount
from app.config import ensure_runtime_directories, load_settings
from app.telethon.config import get_api_credentials
from app.telethon.proxy import build_proxy, proxy_signature

logger = logging.getLogger(__name__)


class TelethonClientManager:
    """Manager for Telethon client instances."""

    def __init__(self):
        self.clients: dict[int, TelegramClient] = {}
        self.proxy_signatures: dict[int, tuple | None] = {}

    async def get_client(self, account: AdvertisingAccount) -> TelegramClient:
        """Get or create a Telethon client for an advertising account."""
        account_id = account.id
        current_signature = proxy_signature(account)
        if (
            account_id in self.clients
            and self.proxy_signatures.get(account_id) != current_signature
        ):
            await self.disconnect_client(account_id)

        if account_id not in self.clients:
            api_id, api_hash = get_api_credentials()
            settings = load_settings(require_secrets=False)
            ensure_runtime_directories(settings)
            session_path = settings.sessions_dir / account.telethon_session
            client = TelegramClient(
                str(session_path),
                api_id,
                api_hash,
                proxy=build_proxy(account),
            )
            await client.connect()
            self.clients[account_id] = client
            self.proxy_signatures[account_id] = current_signature
            logger.info("Connected Telethon client for account %s", account_id)

        return self.clients[account_id]

    async def disconnect_client(self, account_id: int) -> None:
        """Disconnect a cached Telethon client."""
        if account_id in self.clients:
            client = self.clients[account_id]
            await client.disconnect()
            del self.clients[account_id]
            self.proxy_signatures.pop(account_id, None)
            logger.info("Disconnected Telethon client for account %s", account_id)

    async def disconnect_all(self) -> None:
        """Disconnect all cached clients."""
        for account_id in list(self.clients.keys()):
            await self.disconnect_client(account_id)

    async def send_message(
        self, account: AdvertisingAccount, chat_id: str, message: str
    ) -> bool:
        """Send a message to a chat. Returns True if successful."""
        try:
            client = await self.get_client(account)
            await client.send_message(chat_id, message)
            logger.info("Message sent to %s via account %s", chat_id, account.id)
            return True
        except Exception as error:
            logger.error("Failed to send message to %s: %s", chat_id, error)
            return False
