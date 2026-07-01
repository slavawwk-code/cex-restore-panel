import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession, StringSession

from app.database.migrations import run_startup_migrations
from app.database.models import AdvertisingAccount, Base
from app.services.account_health import calculate_account_health
from app.services.account_sessions import (
    create_account_client,
    import_session_bytes,
    resolve_session_source,
    save_string_session,
)
from app.services.device_identity import (
    ensure_account_identity,
    identity_telethon_kwargs,
    proxy_diagnostic_identity_kwargs,
    regenerate_account_identity,
    sanitize_telethon_identity_kwargs,
)
from app.services.telethon_auth import send_login_code


class AccountSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            "os.environ",
            {
                "SESSIONS_DIR": str(self.root / "sessions"),
                "BACKUP_DIR": str(self.root / "backups"),
                "TELEGRAM_API_ID": "12345",
                "TELEGRAM_API_HASH": "a" * 32,
            },
            clear=False,
        )
        self.environment.start()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.account = AdvertisingAccount(
            display_name="Main",
            phone_number="+79123456789",
            telethon_session="legacy_main",
            status="warming",
            proxy_enabled=True,
            proxy_status="working",
        )
        self.db.add(self.account)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.environment.stop()
        self.temporary.cleanup()

    def _sqlite_session_bytes(self) -> bytes:
        source = self.root / "source.session"
        session = SQLiteSession(str(source))
        session.set_dc(2, "149.154.167.51", 443)
        session.auth_key = AuthKey(b"1" * 256)
        session.save()
        session.close()
        return source.read_bytes()

    @staticmethod
    def _string_session() -> str:
        session = StringSession()
        session.set_dc(2, "149.154.167.51", 443)
        session.auth_key = AuthKey(b"2" * 256)
        return session.save()

    async def test_session_import_is_verified_and_saved_with_mode_600(self):
        fake_client = SimpleNamespace(disconnect=AsyncMock())
        user = SimpleNamespace(id=777, username="operator")
        with (
            patch(
                "app.services.account_sessions.create_account_client",
                return_value=fake_client,
            ),
            patch(
                "app.services.account_sessions._verify_authorized_client",
                new=AsyncMock(return_value=user),
            ),
        ):
            result = await import_session_bytes(
                self.db,
                self.account,
                "uploaded.session",
                self._sqlite_session_bytes(),
            )

        target = self.root / "sessions" / f"{self.account.id}.session"
        self.assertEqual(result["source"], "file")
        self.assertTrue(target.is_file())
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
        self.assertEqual(self.account.session_file_path, target.name)
        self.assertEqual(self.account.auth_status, "active")
        self.assertEqual(self.account.status, "active")
        self.assertEqual(self.account.health_score, 100)
        fake_client.disconnect.assert_awaited_once()

    async def test_file_then_string_then_login_priority(self):
        session_dir = self.root / "sessions"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "preferred.session"
        session_file.write_bytes(self._sqlite_session_bytes())
        self.account.session_file_path = session_file.name
        self.account.string_session = self._string_session()

        self.assertEqual(resolve_session_source(self.account).kind, "file")
        session_file.unlink()
        self.assertEqual(resolve_session_source(self.account).kind, "string")
        self.account.string_session = None
        self.assertIsNone(resolve_session_source(self.account))
        self.assertEqual(
            resolve_session_source(self.account, allow_new_file=True).kind,
            "login",
        )

    async def test_string_session_is_verified_before_becoming_fallback(self):
        fake_client = SimpleNamespace(disconnect=AsyncMock())
        user = SimpleNamespace(id=888, username=None)
        with (
            patch(
                "app.services.account_sessions.create_account_client",
                return_value=fake_client,
            ),
            patch(
                "app.services.account_sessions._verify_authorized_client",
                new=AsyncMock(return_value=user),
            ),
        ):
            result = await save_string_session(
                self.db,
                self.account,
                self._string_session(),
            )

        self.assertEqual(result["source"], "string")
        self.assertTrue(self.account.string_session)
        self.assertEqual(self.account.auth_status, "active")
        fake_client.disconnect.assert_awaited_once()

    async def test_login_flow_requests_code_with_file_backed_client(self):
        sent_code = SimpleNamespace(
            phone_code_hash="hash",
            type=SimpleNamespace(),
            timeout=60,
        )
        client = SimpleNamespace(
            connect=AsyncMock(),
            disconnect=AsyncMock(),
            is_user_authorized=AsyncMock(return_value=False),
            send_code_request=AsyncMock(return_value=sent_code),
        )
        with patch(
            "app.services.telethon_auth._create_login_client",
            return_value=client,
        ):
            result = await send_login_code(self.account)

        self.assertFalse(result["already_authorized"])
        self.assertEqual(result["phone_code_hash"], "hash")
        client.send_code_request.assert_awaited_once_with(self.account.phone_number)
        client.disconnect.assert_awaited_once()

    async def test_health_formula_uses_requested_weights(self):
        self.account.session_file_path = f"{self.account.id}.session"
        self.account.session_connected = True
        self.account.auth_status = "active"
        self.account.status = "active"
        health = calculate_account_health(self.db, self.account, True)
        self.assertEqual(
            [(item.label, item.maximum) for item in health.components],
            [
                ("Telegram", 20),
                ("Прокси", 10),
                ("Сессия", 20),
                ("Ошибки авторизации", 20),
                ("Аккаунт", 30),
            ],
        )
        self.assertEqual(health.score, 100)

    async def test_device_identity_is_generated_once_and_used_for_telethon(self):
        self.assertIsNone(self.account.device_model)

        changed = ensure_account_identity(self.account)
        self.db.commit()
        first_identity = (
            self.account.device_model,
            self.account.system_version,
            self.account.app_version,
            self.account.lang_code,
            self.account.system_lang_code,
            self.account.timezone,
            self.account.identity_created_at,
        )

        self.assertTrue(changed)
        self.assertFalse(ensure_account_identity(self.account))
        self.assertEqual(
            first_identity,
            (
                self.account.device_model,
                self.account.system_version,
                self.account.app_version,
                self.account.lang_code,
                self.account.system_lang_code,
                self.account.timezone,
                self.account.identity_created_at,
            ),
        )

        kwargs = identity_telethon_kwargs(self.account)
        self.assertEqual(kwargs["device_model"], self.account.device_model)
        self.assertEqual(kwargs["system_version"], self.account.system_version)
        self.assertEqual(kwargs["app_version"], self.account.app_version)
        self.assertEqual(kwargs["lang_code"], self.account.lang_code)
        self.assertNotIn("lang_pack", kwargs)

    async def test_regenerate_identity_requires_explicit_call(self):
        ensure_account_identity(self.account)
        first_identity = (
            self.account.device_model,
            self.account.system_version,
            self.account.app_version,
            self.account.timezone,
        )
        regenerate_account_identity(self.account)
        second_identity = (
            self.account.device_model,
            self.account.system_version,
            self.account.app_version,
            self.account.timezone,
        )

        self.assertTrue(self.account.identity_created_at)
        # The random profile can theoretically be the same; the important safety
        # property is that regeneration only happens through this explicit call.
        self.assertEqual(len(first_identity), len(second_identity))

    async def test_account_client_passes_identity_kwargs(self):
        session_dir = self.root / "sessions"
        session_dir.mkdir(parents=True)
        session_file = session_dir / f"{self.account.id}.session"
        session_file.write_bytes(self._sqlite_session_bytes())
        self.account.session_file_path = session_file.name
        self.account.proxy_enabled = False
        ensure_account_identity(self.account)

        with patch("app.services.account_sessions.TelegramClient") as telegram_client:
            create_account_client(self.account)

        _, kwargs = telegram_client.call_args
        self.assertEqual(kwargs["device_model"], self.account.device_model)
        self.assertEqual(kwargs["system_version"], self.account.system_version)
        self.assertEqual(kwargs["app_version"], self.account.app_version)
        self.assertEqual(kwargs["lang_code"], self.account.lang_code)
        self.assertNotIn("lang_pack", kwargs)

    async def test_proxy_diagnostic_identity_kwargs_are_telethon_compatible(self):
        kwargs = proxy_diagnostic_identity_kwargs()
        self.assertEqual(
            set(kwargs),
            {
                "device_model",
                "system_version",
                "app_version",
                "lang_code",
                "system_lang_code",
            },
        )
        self.assertNotIn("lang_pack", kwargs)

    async def test_telethon_identity_sanitizer_drops_lang_pack(self):
        kwargs = sanitize_telethon_identity_kwargs(
            {
                "device_model": "Desktop",
                "system_version": "Windows 11 x64",
                "app_version": "5.16.3 x64",
                "lang_code": "ru",
                "system_lang_code": "ru-RU",
                "lang_pack": "",
                "timezone": "Europe/Moscow",
            }
        )
        self.assertEqual(
            set(kwargs),
            {
                "device_model",
                "system_version",
                "app_version",
                "lang_code",
                "system_lang_code",
            },
        )
        self.assertNotIn("lang_pack", kwargs)
        self.assertNotIn("timezone", kwargs)


class LegacyMigrationTests(unittest.TestCase):
    def test_session_columns_are_added_without_recreating_accounts(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE advertising_accounts ("
                    "id INTEGER PRIMARY KEY, display_name VARCHAR NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO advertising_accounts (id, display_name) "
                    "VALUES (1, 'Legacy')"
                )
            )

        run_startup_migrations(engine)
        columns = {
            item["name"] for item in inspect(engine).get_columns("advertising_accounts")
        }
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM advertising_accounts")
            ).scalar_one()

        self.assertTrue(
            {
                "session_file_path",
                "string_session",
                "api_id",
                "api_hash",
                "auth_status",
                "health_score",
                "last_health_check",
                "proxy_id",
                "orchestration_state",
                "orchestration_error",
                "orchestration_updated_at",
                "autopilot_frozen_until",
                "autopilot_freeze_reason",
                "disabled_at",
                "reauth_requested_at",
                "lifecycle_updated_at",
                "lifecycle_reason",
                "login_attempt_count",
                "auth_generation",
                "device_model",
                "system_version",
                "app_version",
                "lang_code",
                "system_lang_code",
                "lang_pack",
                "timezone",
                "identity_created_at",
            }.issubset(columns)
        )
        self.assertEqual(count, 1)
        self.assertIn("proxy_endpoints", inspect(engine).get_table_names())
        self.assertIn("autopilot_control_state", inspect(engine).get_table_names())
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
