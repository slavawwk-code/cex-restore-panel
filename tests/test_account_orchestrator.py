import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from telethon.errors import SessionPasswordNeededError

from app.database.models import AdvertisingAccount, Base
from app.services.account_orchestrator import (
    AccountOrchestrator,
    AccountState,
    OrchestratorError,
    _LoginJob,
)
from app.services.proxy import ParsedProxy, ProxyTestResult


class FakeClientManager:
    def __init__(self):
        self.client = object()
        self.disconnect_all = AsyncMock()
        self.disconnect_client = AsyncMock()
        self.get_client_calls = 0

    async def get_client(self, _account):
        self.get_client_calls += 1
        return self.client


class FakeSentCode:
    phone_code_hash = "hash-123"
    timeout = 120

    class type:
        pass


class FakeLoginClient:
    def __init__(self):
        self.connected = False
        self.sign_in_clients: list[int] = []
        self.disconnected = False
        self.sent_to_phone: str | None = None

    async def connect(self):
        self.connected = True

    def is_connected(self):
        return self.connected

    async def disconnect(self):
        self.disconnected = True
        self.connected = False

    async def is_user_authorized(self):
        return False

    async def send_code_request(self, phone):
        self.sent_to_phone = phone
        return FakeSentCode()

    async def sign_in(self, *args, **kwargs):
        self.sign_in_clients.append(id(self))
        if kwargs.get("password"):
            return True
        raise SessionPasswordNeededError(request=None)


class SlowLoginClient(FakeLoginClient):
    async def send_code_request(self, phone):
        await asyncio.sleep(0.05)
        return await super().send_code_request(phone)


class OrchestratorConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        session = self.session_factory()
        for index in range(1, 10):
            session.add(
                AdvertisingAccount(
                    id=index,
                    display_name=f"Account {index}",
                    phone_number=f"+700000000{index}",
                    telethon_session=f"session_{index}",
                    status="active",
                )
            )
        session.commit()
        session.close()
        self.manager = FakeClientManager()

    def tearDown(self):
        self.engine.dispose()

    def _orchestrator(self, **overrides):
        values = {
            "max_clients": 3,
            "login_concurrency": 2,
            "health_batch_size": 3,
            "global_delay_seconds": 0,
            "account_delay_seconds": 0,
            "session_factory": self.session_factory,
            "client_manager": self.manager,
        }
        values.update(overrides)
        return AccountOrchestrator(**values)

    async def test_login_queue_never_exceeds_worker_limit(self):
        orchestrator = self._orchestrator()
        active = 0
        maximum = 0

        async def execute(job):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"account_id": job.account_id}

        with patch.object(orchestrator, "_execute_login_job", side_effect=execute):
            results = await asyncio.gather(
                *(orchestrator.login_account(index) for index in range(1, 7))
            )
        await orchestrator.stop()

        self.assertEqual(maximum, 2)
        self.assertEqual(len(results), 6)
        self.assertEqual(orchestrator.login_queue_size, 0)

    async def test_global_client_limit_caps_different_accounts(self):
        orchestrator = self._orchestrator(max_clients=3)
        active = 0
        maximum = 0

        async def operation(_client, _account):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return True

        await asyncio.gather(
            *(
                orchestrator.run_client_operation(index, "test", operation)
                for index in range(1, 9)
            )
        )
        await orchestrator.stop()
        self.assertEqual(maximum, 3)

    async def test_health_cycle_processes_bounded_batches(self):
        orchestrator = self._orchestrator(health_batch_size=3)
        active = 0
        maximum = 0

        async def validate(account_id):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.005)
            active -= 1
            return {"connected": True, "account_id": account_id}

        with patch.object(orchestrator, "validate_account", side_effect=validate):
            result = await orchestrator.run_health_cycle()
        await orchestrator.stop()

        self.assertEqual(len(result), 9)
        self.assertEqual(maximum, 3)

    async def test_get_account_state_returns_persisted_state(self):
        session = self.session_factory()
        account = session.get(AdvertisingAccount, 1)
        account.orchestration_state = AccountState.DEGRADED.value
        account.orchestration_error = "Proxy timeout"
        session.commit()
        session.close()

        orchestrator = self._orchestrator()
        state = await orchestrator.get_account_state(1)
        await orchestrator.stop()

        self.assertEqual(state["state"], "DEGRADED")
        self.assertEqual(state["error"], "Proxy timeout")

    async def test_unverified_proxy_is_checked_before_telethon_use(self):
        session = self.session_factory()
        account = session.get(AdvertisingAccount, 1)
        account.proxy_enabled = True
        account.proxy_type = "SOCKS5"
        account.proxy_host = "proxy.example"
        account.proxy_port = 1080
        account.proxy_status = "unknown"
        session.commit()
        session.close()

        async def failed_check(_session, checked_account):
            checked_account.proxy_status = "failed"
            checked_account.proxy_last_error = "Connection timeout"
            _session.commit()
            return ProxyTestResult("SOCKS5", False, "Connection timeout")

        orchestrator = self._orchestrator()
        with patch(
            "app.services.account_orchestrator.run_fast_proxy_check",
            side_effect=failed_check,
        ):
            with self.assertRaises(OrchestratorError):
                await orchestrator.run_client_operation(1, "test", AsyncMock())
        await orchestrator.stop()

        self.assertEqual(self.manager.get_client_calls, 0)

    async def test_2fa_login_reuses_same_auth_client_across_code_and_password(self):
        orchestrator = self._orchestrator()
        login_client = FakeLoginClient()

        with (
            patch(
                "app.services.account_orchestrator.create_account_client",
                return_value=login_client,
            ) as create_client,
            patch("app.services.account_orchestrator.finalize_login_session"),
            patch(
                "app.services.account_orchestrator.check_session_status",
                new=AsyncMock(return_value={"connected": True}),
            ),
        ):
            request_result = await orchestrator.login_account(1)
            code_result = await orchestrator.login_account(
                1,
                action="code",
                code="12345",
                phone_code_hash=request_result["phone_code_hash"],
            )
            password_result = await orchestrator.login_account(
                1,
                action="password",
                password="cloud-password",
            )

        await orchestrator.stop()

        self.assertFalse(request_result["already_authorized"])
        self.assertTrue(code_result["requires_password"])
        self.assertTrue(password_result["success"])
        self.assertEqual(create_client.call_count, 1)
        self.assertEqual(len(set(login_client.sign_in_clients)), 1)
        self.assertTrue(login_client.disconnected)

    async def test_request_code_twice_is_blocked_without_force_reset(self):
        orchestrator = self._orchestrator()
        login_client = FakeLoginClient()

        with patch(
            "app.services.account_orchestrator.create_account_client",
            return_value=login_client,
        ) as create_client:
            first = await orchestrator.login_account(1)
            with self.assertRaises(OrchestratorError) as caught:
                await orchestrator.login_account(1)

        await orchestrator.stop()

        self.assertEqual(first["phone_code_hash"], "hash-123")
        self.assertIn("AUTH FLOW IN PROGRESS", str(caught.exception))
        self.assertEqual(create_client.call_count, 1)

    async def test_force_reset_clears_old_auth_context(self):
        orchestrator = self._orchestrator()
        first_client = FakeLoginClient()
        second_client = FakeLoginClient()

        with patch(
            "app.services.account_orchestrator.create_account_client",
            side_effect=[first_client, second_client],
        ):
            await orchestrator.login_account(1)
            await orchestrator.login_account(1, force_reset=True)

        await orchestrator.stop()

        self.assertTrue(first_client.disconnected)
        self.assertTrue(second_client.disconnected)

    async def test_proxy_change_during_auth_is_rejected(self):
        orchestrator = self._orchestrator()
        login_client = FakeLoginClient()
        proxy_config = ParsedProxy(
            proxy_type="SOCKS5",
            host="127.0.0.1",
            port=1080,
            username=None,
            password=None,
            candidate_types=("SOCKS5",),
        )

        with patch(
            "app.services.account_orchestrator.create_account_client",
            return_value=login_client,
        ):
            await orchestrator.login_account(1)
            with self.assertRaises(OrchestratorError) as caught:
                await orchestrator.assign_proxy(
                    1,
                    proxy_config=proxy_config,
                    validate=False,
                )

        await orchestrator.stop()
        self.assertIn("AUTH FLOW IN PROGRESS", str(caught.exception))

    async def test_auth_context_ttl_expiry_resets_account_state(self):
        orchestrator = self._orchestrator()
        login_client = FakeLoginClient()

        with patch(
            "app.services.account_orchestrator.create_account_client",
            return_value=login_client,
        ):
            await orchestrator.login_account(1)

        context = orchestrator._auth_contexts[1]
        context.expires_at = time.monotonic() - 1
        expired = await orchestrator._expire_auth_context_if_needed(1)
        await orchestrator.stop()

        session = self.session_factory()
        try:
            account = session.get(AdvertisingAccount, 1)
            self.assertTrue(expired)
            self.assertNotIn(1, orchestrator._auth_contexts)
            self.assertEqual(account.orchestration_state, AccountState.CREATED.value)
            self.assertEqual(account.orchestration_error, "AUTH FLOW EXPIRED")
            self.assertTrue(login_client.disconnected)
        finally:
            session.close()

    async def test_concurrent_login_attempts_are_blocked(self):
        orchestrator = self._orchestrator()
        slow_client = SlowLoginClient()

        async def slow_execute(job):
            await asyncio.sleep(0.05)
            return {"ok": job.account_id}

        with (
            patch(
                "app.services.account_orchestrator.create_account_client",
                return_value=slow_client,
            ),
            patch.object(
                orchestrator,
                "_execute_login_job",
                side_effect=slow_execute,
            ),
        ):
            first = asyncio.create_task(orchestrator.login_account(1))
            await asyncio.sleep(0)
            with self.assertRaises(OrchestratorError) as caught:
                await orchestrator.login_account(1)
            await first

        await orchestrator.stop()
        self.assertIn("AUTH FLOW IN PROGRESS", str(caught.exception))

    async def test_password_step_without_auth_context_does_not_create_client(self):
        orchestrator = self._orchestrator()
        future = asyncio.get_running_loop().create_future()

        with patch(
            "app.services.account_orchestrator.create_account_client",
            return_value=FakeLoginClient(),
        ) as create_client:
            with self.assertRaises(OrchestratorError):
                await orchestrator._execute_login_job(
                    _LoginJob(
                        1,
                        "password",
                        password="cloud-password",
                        auth_generation=0,
                        future=future,
                    )
                )

        await orchestrator.stop()
        create_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
