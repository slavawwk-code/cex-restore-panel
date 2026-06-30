import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import AdvertisingAccount, Base, Chat
from app.services.account_lifecycle_manager import (
    AccountLifecycleError,
    AccountLifecycleManager,
)
from app.services.account_orchestrator import (
    AccountOrchestrator,
    AccountState,
    OrchestratorError,
)


class FakeClientManager:
    def __init__(self):
        self.clients = {}
        self.disconnect_all = AsyncMock()
        self.disconnect_client = AsyncMock(side_effect=self._disconnect)

    async def _disconnect(self, account_id):
        self.clients.pop(account_id, None)

    async def get_client(self, account):
        client = object()
        self.clients[account.id] = client
        return client


class AccountLifecycleManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.temporary.name) / "sessions"
        self.sessions_dir.mkdir()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.client_manager = FakeClientManager()
        self.orchestrator = AccountOrchestrator(
            max_clients=3,
            login_concurrency=2,
            health_batch_size=3,
            global_delay_seconds=0,
            account_delay_seconds=0,
            session_factory=self.session_factory,
            client_manager=self.client_manager,
        )
        self.manager = AccountLifecycleManager(
            self.orchestrator,
            session_factory=self.session_factory,
            sessions_dir=self.sessions_dir,
        )

    async def asyncTearDown(self):
        await self.orchestrator.stop()
        self.engine.dispose()
        self.temporary.cleanup()

    def _create_account(self, account_id: int = 1, session_name: str | None = None):
        name = session_name or str(account_id)
        session = self.session_factory()
        account = AdvertisingAccount(
            id=account_id,
            display_name=f"Account {account_id}",
            phone_number=f"+799900000{account_id:02d}",
            telethon_session=name,
            session_file_path=f"{name}.session",
            string_session="fallback-secret",
            status="active",
            auth_status="active",
            session_connected=True,
            orchestration_state=AccountState.ACTIVE.value,
            proxy_enabled=True,
            proxy_type="SOCKS5",
            proxy_host="proxy.example",
            proxy_port=1080,
            proxy_status="working",
        )
        session.add(account)
        session.commit()
        session.close()
        file_path = self.sessions_dir / f"{name}.session"
        file_path.write_bytes(b"session-data")
        file_path.chmod(0o600)
        return file_path

    async def test_disable_keeps_database_and_session_file(self):
        file_path = self._create_account()

        result = await self.manager.disable_account(1)
        session = self.session_factory()
        account = session.get(AdvertisingAccount, 1)

        self.assertEqual(result.result, "success")
        self.assertEqual(account.status, "disabled")
        self.assertTrue(file_path.exists())
        self.assertTrue(account.session_connected)
        self.assertIn(1, self.orchestrator._disabled_accounts)
        session.close()

    async def test_hard_delete_removes_database_children_and_session(self):
        file_path = self._create_account()
        session = self.session_factory()
        session.add(
            Chat(
                advertising_account_id=1,
                title="Target",
                username_or_chat_id="@target",
                status="active",
                is_active=True,
            )
        )
        session.commit()
        session.close()
        self.client_manager.clients[1] = object()

        result = await self.manager.delete_account(1)
        session = self.session_factory()

        self.assertEqual(result.result, "success")
        self.assertIsNone(session.get(AdvertisingAccount, 1))
        self.assertEqual(session.query(Chat).count(), 0)
        self.assertFalse(file_path.exists())
        self.assertNotIn(1, self.client_manager.clients)
        self.assertNotIn(1, self.orchestrator._account_locks)
        session.close()

    async def test_delete_is_blocked_while_account_is_busy(self):
        file_path = self._create_account()
        self.orchestrator._account_operations[1] = 1

        with self.assertRaises(AccountLifecycleError):
            await self.manager.delete_account(1)

        session = self.session_factory()
        self.assertIsNotNone(session.get(AdvertisingAccount, 1))
        self.assertTrue(file_path.exists())
        session.close()
        self.orchestrator._account_operations.pop(1, None)

    async def test_force_delete_waits_for_running_operation(self):
        self._create_account()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def running_operation(_client, _account):
            entered.set()
            await release.wait()
            return True

        operation_task = asyncio.create_task(
            self.orchestrator.run_client_operation(1, "test", running_operation)
        )
        await entered.wait()
        delete_task = asyncio.create_task(self.manager.delete_account(1, force=True))
        await asyncio.sleep(0.01)
        self.assertFalse(delete_task.done())

        release.set()
        await operation_task
        result = await delete_task

        self.assertEqual(result.result, "success")

    async def test_reauth_archives_file_and_clears_runtime_bindings(self):
        file_path = self._create_account()

        result = await self.manager.reauth_account(1)
        session = self.session_factory()
        account = session.get(AdvertisingAccount, 1)
        archived = list((self.sessions_dir / "reauth_archive").glob("*.session"))

        self.assertEqual(result.next_action, "auth_methods_1")
        self.assertFalse(file_path.exists())
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(account.status, "warming")
        self.assertEqual(account.orchestration_state, "REAUTH_REQUIRED")
        self.assertFalse(account.session_connected)
        self.assertIsNone(account.session_file_path)
        self.assertIsNone(account.string_session)
        self.assertIsNone(account.proxy_id)
        self.assertFalse(account.proxy_enabled)
        self.assertEqual(account.auth_generation, 1)
        self.assertNotIn(1, self.orchestrator._disabled_accounts)
        session.close()

    async def test_shared_legacy_session_is_not_deleted(self):
        shared_file = self._create_account(1, "shared")
        session = self.session_factory()
        session.add(
            AdvertisingAccount(
                id=2,
                display_name="Account 2",
                phone_number="+79990000002",
                telethon_session="shared",
                session_file_path="shared.session",
                status="active",
            )
        )
        session.commit()
        session.close()

        await self.manager.delete_account(1)

        self.assertTrue(shared_file.exists())
        session = self.session_factory()
        self.assertIsNotNone(session.get(AdvertisingAccount, 2))
        session.close()

    async def test_reauth_cancels_stale_queued_login_flow(self):
        self._create_account()
        self.orchestrator.pause_login_queue()
        login_task = asyncio.create_task(self.orchestrator.login_account(1))
        await asyncio.sleep(0)
        self.assertTrue(self.orchestrator.is_account_busy(1))

        await self.manager.reauth_account(1)

        with self.assertRaises(OrchestratorError):
            await login_task
        self.assertFalse(self.orchestrator.is_account_busy(1))


if __name__ == "__main__":
    unittest.main()
