import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, inspect, text

from app.database.migrations import ACCOUNT_PROXY_COLUMNS, run_startup_migrations
from app.database.models import AdvertisingAccount
from app.services.proxy import (
    ProxyConfigurationError,
    ProxyDetectionResult,
    ProxyStringParseError,
    ProxyTestResult,
    detect_working_proxy_type,
    format_proxy_confirmation,
    format_proxy_detection_failure,
    format_proxy_status_card,
    parse_proxy_string,
    run_fast_proxy_check,
    run_full_proxy_diagnostics,
    save_detected_proxy,
    validate_proxy_settings,
)
from app.telethon.proxy import build_proxy


class ProxyConfigurationTests(unittest.TestCase):
    def test_supported_paste_formats(self):
        cases = {
            "proxy.example:1080": (None, None, None),
            "proxy.example:1080:user:password": (
                None,
                "user",
                "password",
            ),
            "user:password@proxy.example:1080": (
                None,
                "user",
                "password",
            ),
            "http://user:password@proxy.example:8080": (
                "HTTP",
                "user",
                "password",
            ),
            "https://user:password@proxy.example:8080": (
                "HTTP",
                "user",
                "password",
            ),
            "socks5://user:password@proxy.example:1080": (
                "SOCKS5",
                "user",
                "password",
            ),
            "socks5://proxy.example:1080:user:password": (
                "SOCKS5",
                "user",
                "password",
            ),
            "socks4://user:password@proxy.example:1080": (
                "SOCKS4",
                "user",
                "password",
            ),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                parsed = parse_proxy_string(value)
                self.assertEqual(
                    (parsed.proxy_type, parsed.username, parsed.password), expected
                )
                self.assertEqual(parsed.host, "proxy.example")

    def test_url_encoded_credentials_are_decoded(self):
        parsed = parse_proxy_string(
            "socks5://user%40mail:p%3Ass@proxy.example:1080"
        )
        self.assertEqual(parsed.username, "user@mail")
        self.assertEqual(parsed.password, "p:ss")

    def test_scheme_seller_host_port_user_password_format(self):
        parsed = parse_proxy_string("socks5://83.138.52.101:62271:epcdmWGm:zdn4Vy9A")
        self.assertEqual(parsed.proxy_type, "SOCKS5")
        self.assertEqual(parsed.host, "83.138.52.101")
        self.assertEqual(parsed.port, 62271)
        self.assertEqual(parsed.username, "epcdmWGm")
        self.assertEqual(parsed.password, "zdn4Vy9A")
        self.assertEqual(parsed.candidate_types, ("SOCKS5",))

    def test_password_is_not_exposed_by_parsed_value_repr(self):
        parsed = parse_proxy_string("proxy.example:1080:user:top-secret")
        self.assertNotIn("top-secret", repr(parsed))
        self.assertNotIn("top-secret", format_proxy_confirmation(parsed))
        self.assertIn("••••••••", format_proxy_confirmation(parsed))

    def test_status_card_masks_password(self):
        account = AdvertisingAccount(
            proxy_enabled=True,
            proxy_type="HTTP",
            proxy_host="proxy.example",
            proxy_port=8080,
            proxy_username="operator",
            proxy_password="top-secret",
            proxy_status="working",
            proxy_latency_ms=182,
        )
        output = format_proxy_status_card(account)
        self.assertNotIn("top-secret", output)
        self.assertNotIn("Пароль", output)
        self.assertIn("182 ms", output)

    def test_explicit_schemes_have_one_candidate_type(self):
        cases = {
            "socks5://user:password@proxy.example:1080": ("SOCKS5",),
            "socks4://user:password@proxy.example:1080": ("SOCKS4",),
            "http://user:password@proxy.example:8080": ("HTTP",),
            "https://user:password@proxy.example:8080": ("HTTP",),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_proxy_string(value).candidate_types, expected)

    def test_no_scheme_uses_detection_order(self):
        parsed = parse_proxy_string("proxy.example:1080:user:password")
        self.assertIsNone(parsed.proxy_type)
        self.assertEqual(parsed.candidate_types, ("SOCKS5", "HTTP", "SOCKS4"))

    def test_invalid_paste_formats_are_rejected(self):
        invalid_values = (
            "",
            "proxy.example",
            "proxy.example:not-a-port",
            "proxy.example:70000",
            "user@proxy.example:1080",
            "ftp://user:password@proxy.example:21",
            "http://proxy.example:8080/path",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ProxyStringParseError):
                    parse_proxy_string(value)

    def test_supported_proxy_types_build_telethon_config(self):
        for proxy_type in ("SOCKS5", "SOCKS4", "HTTP"):
            with self.subTest(proxy_type=proxy_type):
                account = AdvertisingAccount(
                    proxy_enabled=True,
                    proxy_type=proxy_type,
                    proxy_host="127.0.0.1",
                    proxy_port=1080,
                    proxy_username="operator",
                    proxy_password="secret",
                )
                proxy = build_proxy(account)
                self.assertEqual(proxy["proxy_type"], proxy_type.lower())
                self.assertEqual(proxy["addr"], "127.0.0.1")
                self.assertEqual(proxy["port"], 1080)

    def test_disabled_proxy_returns_none(self):
        account = AdvertisingAccount(proxy_enabled=False)
        self.assertIsNone(build_proxy(account))

    def test_invalid_port_is_rejected(self):
        with self.assertRaises(ProxyConfigurationError):
            validate_proxy_settings("SOCKS5", "127.0.0.1", 70000)


class ProxyMigrationTests(unittest.TestCase):
    def test_existing_account_table_receives_proxy_columns(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE advertising_accounts "
                    "(id INTEGER PRIMARY KEY, display_name VARCHAR NOT NULL)"
                )
            )

        run_startup_migrations(engine)
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("advertising_accounts")
        }
        self.assertTrue(set(ACCOUNT_PROXY_COLUMNS).issubset(columns))
        self.assertIn("proxy_check_history", inspect(engine).get_table_names())


class ProxyDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_check_uses_saved_type_only_and_updates_working_status(self):
        account = AdvertisingAccount(
            id=1,
            proxy_enabled=True,
            proxy_type="HTTP",
            proxy_host="proxy.example",
            proxy_port=8080,
            proxy_status="unknown",
        )
        session = MagicMock()
        mock_test = AsyncMock(
            return_value=ProxyTestResult("HTTP", True, latency_ms=120)
        )
        with patch("app.services.proxy.test_proxy_with_type", mock_test):
            result = await run_fast_proxy_check(session, account)

        self.assertTrue(result.success)
        self.assertEqual(mock_test.await_count, 1)
        self.assertEqual(mock_test.await_args.args[1], "HTTP")
        self.assertEqual(account.proxy_status, "working")
        self.assertEqual(account.proxy_latency_ms, 120)
        self.assertIsNotNone(account.proxy_last_success_at)

    async def test_fast_check_updates_failed_status(self):
        account = AdvertisingAccount(
            id=1,
            proxy_enabled=True,
            proxy_type="SOCKS5",
            proxy_host="proxy.example",
            proxy_port=1080,
            proxy_status="working",
        )
        session = MagicMock()
        with patch(
            "app.services.proxy.test_proxy_with_type",
            AsyncMock(return_value=ProxyTestResult("SOCKS5", False, "тайм-аут")),
        ):
            await run_fast_proxy_check(session, account)

        self.assertEqual(account.proxy_status, "failed")
        self.assertEqual(account.proxy_last_error, "тайм-аут")
        self.assertIsNone(account.proxy_latency_ms)

    async def test_full_diagnostics_tries_all_types_when_type_is_unknown(self):
        account = AdvertisingAccount(
            id=1,
            proxy_enabled=True,
            proxy_type=None,
            proxy_host="proxy.example",
            proxy_port=1080,
            proxy_status="unknown",
        )
        session = MagicMock()
        detection = ProxyDetectionResult(
            True,
            "HTTP",
            (
                ProxyTestResult("SOCKS5", False, "ошибка"),
                ProxyTestResult("HTTP", True, latency_ms=90),
            ),
        )
        mock_detect = AsyncMock(return_value=detection)
        with patch("app.services.proxy.detect_working_proxy_type", mock_detect):
            result = await run_full_proxy_diagnostics(session, account)

        self.assertTrue(result.success)
        self.assertEqual(
            mock_detect.await_args.kwargs["candidate_types"],
            ("SOCKS5", "HTTP", "SOCKS4"),
        )
        self.assertEqual(account.proxy_type, "HTTP")
        self.assertEqual(account.proxy_detected_type, "HTTP")
        self.assertEqual(account.proxy_status, "working")

    async def test_detection_stops_at_first_success(self):
        config = parse_proxy_string("proxy.example:1080:user:password")
        mock_test = AsyncMock(
            side_effect=[
                ProxyTestResult("SOCKS5", False, "ошибка SOCKS5"),
                ProxyTestResult("HTTP", True),
            ]
        )
        with patch("app.services.proxy.test_proxy_with_type", mock_test):
            result = await detect_working_proxy_type(config)

        self.assertTrue(result.success)
        self.assertEqual(result.detected_type, "HTTP")
        self.assertEqual(
            [call.args[1] for call in mock_test.await_args_list],
            ["SOCKS5", "HTTP"],
        )

    async def test_failure_tries_all_types_and_formats_each_error(self):
        config = parse_proxy_string("proxy.example:1080:user:password")
        mock_test = AsyncMock(
            side_effect=[
                ProxyTestResult("SOCKS5", False, "ошибка 1"),
                ProxyTestResult("HTTP", False, "ошибка 2"),
                ProxyTestResult("SOCKS4", False, "ошибка 3"),
            ]
        )
        with patch("app.services.proxy.test_proxy_with_type", mock_test):
            result = await detect_working_proxy_type(config)

        self.assertFalse(result.success)
        self.assertEqual(
            [call.args[1] for call in mock_test.await_args_list],
            ["SOCKS5", "HTTP", "SOCKS4"],
        )
        output = format_proxy_detection_failure(result)
        self.assertIn("SOCKS5: ошибка 1", output)
        self.assertIn("HTTP: ошибка 2", output)
        self.assertIn("SOCKS4: ошибка 3", output)
        self.assertNotIn("password", output)

    def test_first_successful_type_is_saved(self):
        config = parse_proxy_string("proxy.example:1080:user:password")
        detection = ProxyDetectionResult(
            success=True,
            detected_type="HTTP",
            attempts=(
                ProxyTestResult("SOCKS5", False, "ошибка"),
                ProxyTestResult("HTTP", True),
            ),
        )
        account = AdvertisingAccount(id=1)
        session = MagicMock()

        save_detected_proxy(session, account, config, detection)

        self.assertEqual(account.proxy_type, "HTTP")
        self.assertTrue(account.proxy_enabled)
        self.assertTrue(account.proxy_last_check_success)


if __name__ == "__main__":
    unittest.main()
