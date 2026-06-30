import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    AdvertisingAccount,
    Base,
    Chat,
    ProxyCheckHistory,
    Template,
)
from app.services.account_health import calculate_account_health, health_indicator
from app.services.proxy import ProxyTestResult, _apply_proxy_test_status
from app.ui.cards import format_account_card, format_proxy_history


class HealthScoreTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _healthy_account(self) -> AdvertisingAccount:
        account = AdvertisingAccount(
            display_name="Main <Account>",
            phone_number="+79123456789",
            telethon_session="main",
            status="active",
            session_connected=True,
            proxy_enabled=True,
            proxy_type="SOCKS5",
            proxy_host="83.138.52.101",
            proxy_port=62271,
            proxy_status="working",
            proxy_last_check_success=True,
        )
        template = Template(name="Primary", text="Test template", is_active=True)
        self.session.add_all([account, template])
        self.session.flush()
        self.session.add(
            Chat(
                advertising_account_id=account.id,
                title="Target",
                username_or_chat_id="@target",
                assigned_template_id=template.id,
                status="active",
                is_active=True,
            )
        )
        self.session.commit()
        return account

    def test_healthy_account_scores_100(self):
        account = self._healthy_account()
        health = calculate_account_health(self.session, account, True)
        self.assertEqual(health.score, 100)
        self.assertEqual(health_indicator(health.score), "🟢")

    def test_account_card_masks_phone_and_escapes_name(self):
        account = self._healthy_account()
        health = calculate_account_health(self.session, account, True)
        output = format_account_card(account, health)
        self.assertNotIn("+79123456789", output)
        self.assertIn("+7••••••6789", output)
        self.assertIn("Main &lt;Account&gt;", output)
        self.assertIn("100%", output)

    def test_health_color_boundaries(self):
        self.assertEqual(health_indicator(90), "🟢")
        self.assertEqual(health_indicator(60), "🟡")
        self.assertEqual(health_indicator(59), "🔴")


class ProxyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.account = AdvertisingAccount(
            display_name="Main",
            phone_number="+70000000000",
            telethon_session="main",
            status="active",
            proxy_enabled=True,
            proxy_type="HTTP",
            proxy_host="proxy.example",
            proxy_port=8080,
        )
        self.session.add(self.account)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_only_latest_20_proxy_checks_are_retained(self):
        for latency in range(25):
            _apply_proxy_test_status(
                self.session,
                self.account,
                ProxyTestResult("HTTP", True, latency_ms=latency + 1),
            )
        records = self.session.query(ProxyCheckHistory).all()
        self.assertEqual(len(records), 20)

    def test_history_does_not_render_password(self):
        self.account.proxy_password = "top-secret"
        _apply_proxy_test_status(
            self.session,
            self.account,
            ProxyTestResult("HTTP", False, "Connection timeout"),
        )
        records = self.session.query(ProxyCheckHistory).all()
        output = format_proxy_history(self.account, records)
        self.assertNotIn("top-secret", output)
        self.assertIn("Connection timeout", output)


if __name__ == "__main__":
    unittest.main()
