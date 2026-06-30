import asyncio
import logging
from contextlib import suppress

from aiogram import Bot

from app.database import get_session
from app.database.models import AdvertisingAccount
from app.config import load_settings
from app.services.account_orchestrator import account_orchestrator
from app.services.proxy import format_proxy_timestamp

logger = logging.getLogger(__name__)


async def run_fast_proxy_check(session, account: AdvertisingAccount):
    """Compatibility adapter; production checks pass through the orchestrator."""
    result = await account_orchestrator.check_proxy(account.id, full=False)
    session.expire(account)
    session.refresh(account)
    return result


class ProxyMonitorService:
    """Independent periodic health monitor for configured account proxies."""

    def __init__(
        self,
        bot: Bot,
        interval_seconds: int | None = None,
        owner_telegram_id: int | None = None,
    ) -> None:
        self.bot = bot
        self.interval_seconds = (
            interval_seconds
            if interval_seconds is not None
            else _read_interval_from_environment()
        )
        self.owner_telegram_id = (
            owner_telegram_id
            if owner_telegram_id is not None
            else _read_owner_id_from_environment()
        )
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        """Start monitoring, or return False when disabled by configuration."""
        if self.interval_seconds <= 0:
            logger.info("Proxy monitoring is disabled")
            return False
        if self.running:
            return True
        self._task = asyncio.create_task(self._run(), name="proxy-monitor")
        logger.info(
            "Proxy monitoring started with interval %s seconds",
            self.interval_seconds,
        )
        return True

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Proxy monitoring stopped")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                await self.check_once()
            except Exception:
                logger.exception("Proxy monitoring cycle failed")

    async def check_once(self) -> None:
        """Fast-check configured proxies and notify only on state transitions."""
        session = get_session()
        try:
            accounts = (
                session.query(AdvertisingAccount)
                .filter(
                    AdvertisingAccount.proxy_enabled.is_(True),
                    AdvertisingAccount.proxy_host.is_not(None),
                    AdvertisingAccount.proxy_port.is_not(None),
                    AdvertisingAccount.proxy_type.is_not(None),
                )
                .all()
            )
            for account in accounts:
                previous_status = account.proxy_status or "unknown"
                result = await run_fast_proxy_check(session, account)
                if previous_status == "working" and not result.success:
                    await self._send_failure_alert(account)
                elif previous_status == "failed" and result.success:
                    await self._send_recovery_alert(account)
        finally:
            session.close()

    async def _send_failure_alert(self, account: AdvertisingAccount) -> None:
        last_success = (
            format_proxy_timestamp(account.proxy_last_success_at)
            if account.proxy_last_success_at
            else "—"
        )
        await self._send_alert(
            "🔴 Прокси перестал работать\n\n"
            f"Аккаунт:\n{account.display_name}\n\n"
            f"Прокси:\n{account.proxy_host}:{account.proxy_port}\n\n"
            f"Тип:\n{account.proxy_type}\n\n"
            f"Ошибка:\n{account.proxy_last_error or 'неизвестная ошибка'}\n\n"
            f"Последняя успешная проверка:\n{last_success}"
        )

    async def _send_recovery_alert(self, account: AdvertisingAccount) -> None:
        latency = (
            f"{account.proxy_latency_ms} мс"
            if account.proxy_latency_ms is not None
            else "—"
        )
        await self._send_alert(
            "🟢 Прокси снова работает\n\n"
            f"Аккаунт:\n{account.display_name}\n\n"
            f"Прокси:\n{account.proxy_host}:{account.proxy_port}\n\n"
            f"Тип:\n{account.proxy_type}\n\n"
            f"Задержка:\n{latency}"
        )

    async def _send_alert(self, text: str) -> None:
        if not self.owner_telegram_id:
            logger.warning("Proxy status changed, but OWNER_TELEGRAM_ID is unavailable")
            return
        try:
            await self.bot.send_message(self.owner_telegram_id, text)
        except Exception:
            logger.exception("Could not send proxy status alert to owner")


def _read_interval_from_environment() -> int:
    return load_settings(require_secrets=False).proxy_monitor_interval_seconds


def _read_owner_id_from_environment() -> int | None:
    return load_settings(require_secrets=False).owner_telegram_id
