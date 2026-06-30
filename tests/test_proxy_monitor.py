import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.database.models import AdvertisingAccount
from app.services.proxy import ProxyTestResult
from app.services.proxy_monitor import ProxyMonitorService


def _account(status: str) -> AdvertisingAccount:
    return AdvertisingAccount(
        id=7,
        display_name="Main Account",
        phone_number="+10000000000",
        telethon_session="session",
        proxy_enabled=True,
        proxy_type="SOCKS5",
        proxy_host="83.138.52.101",
        proxy_port=62271,
        proxy_status=status,
    )


class ProxyMonitorTests(unittest.IsolatedAsyncioTestCase):
    def _session_with(self, account):
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [account]
        return session

    async def test_alert_on_working_to_failed(self):
        account = _account("working")
        session = self._session_with(account)
        bot = MagicMock()
        bot.send_message = AsyncMock()

        async def fail_check(_session, checked_account):
            checked_account.proxy_status = "failed"
            checked_account.proxy_last_error = "Connection timeout"
            return ProxyTestResult("SOCKS5", False, "Connection timeout")

        monitor = ProxyMonitorService(bot, 1800, 123)
        with (
            patch("app.services.proxy_monitor.get_session", return_value=session),
            patch("app.services.proxy_monitor.run_fast_proxy_check", side_effect=fail_check),
        ):
            await monitor.check_once()

        bot.send_message.assert_awaited_once()
        self.assertIn("Прокси перестал работать", bot.send_message.await_args.args[1])
        self.assertNotIn("password", bot.send_message.await_args.args[1])

    async def test_repeated_failure_does_not_spam(self):
        account = _account("failed")
        session = self._session_with(account)
        bot = MagicMock()
        bot.send_message = AsyncMock()

        async def fail_check(_session, checked_account):
            checked_account.proxy_status = "failed"
            return ProxyTestResult("SOCKS5", False, "Connection timeout")

        monitor = ProxyMonitorService(bot, 1800, 123)
        with (
            patch("app.services.proxy_monitor.get_session", return_value=session),
            patch("app.services.proxy_monitor.run_fast_proxy_check", side_effect=fail_check),
        ):
            await monitor.check_once()

        bot.send_message.assert_not_awaited()

    async def test_recovery_alert_on_failed_to_working(self):
        account = _account("failed")
        session = self._session_with(account)
        bot = MagicMock()
        bot.send_message = AsyncMock()

        async def successful_check(_session, checked_account):
            checked_account.proxy_status = "working"
            checked_account.proxy_latency_ms = 170
            return ProxyTestResult("SOCKS5", True, latency_ms=170)

        monitor = ProxyMonitorService(bot, 1800, 123)
        with (
            patch("app.services.proxy_monitor.get_session", return_value=session),
            patch(
                "app.services.proxy_monitor.run_fast_proxy_check",
                side_effect=successful_check,
            ),
        ):
            await monitor.check_once()

        bot.send_message.assert_awaited_once()
        self.assertIn("Прокси снова работает", bot.send_message.await_args.args[1])
        self.assertIn("170 мс", bot.send_message.await_args.args[1])

    async def test_zero_interval_disables_monitoring(self):
        monitor = ProxyMonitorService(MagicMock(), 0, 123)
        self.assertFalse(await monitor.start())
        self.assertFalse(monitor.running)


if __name__ == "__main__":
    unittest.main()
