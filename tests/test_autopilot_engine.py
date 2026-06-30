import asyncio
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import AdvertisingAccount, Base, ProxyEndpoint
from app.services.account_orchestrator import AccountOrchestrator, AccountState
from app.services.autopilot_engine import AutopilotEngine, SystemState


class FakeClientManager:
    def __init__(self):
        self.clients = {}
        self.disconnect_all = AsyncMock()
        self.disconnect_client = AsyncMock()

    async def get_client(self, _account):
        return object()


class AutopilotEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        session = self.session_factory()
        for index in range(1, 11):
            session.add(
                AdvertisingAccount(
                    id=index,
                    display_name=f"Account {index}",
                    phone_number=f"+790000000{index:02d}",
                    telethon_session=f"session_{index}",
                    status="active",
                    orchestration_state=AccountState.ACTIVE.value,
                )
            )
        session.commit()
        session.close()
        self.orchestrator = AccountOrchestrator(
            max_clients=5,
            login_concurrency=2,
            health_batch_size=3,
            global_delay_seconds=0,
            account_delay_seconds=0,
            session_factory=self.session_factory,
            client_manager=FakeClientManager(),
        )
        self.autopilot = AutopilotEngine(
            self.orchestrator,
            interval_seconds=10,
            queue_threshold=5,
            recovery_cooldown_seconds=60,
            healthy_clients=5,
            session_factory=self.session_factory,
        )

    async def asyncTearDown(self):
        await self.autopilot.stop()
        await self.orchestrator.stop()
        self.engine.dispose()

    async def test_six_flood_waits_pause_logins_and_degrade(self):
        for _ in range(6):
            self.orchestrator._record_event("flood_wait")

        decision = await self.autopilot.run_once()

        self.assertEqual(decision.state, SystemState.DEGRADED)
        self.assertTrue(self.orchestrator.login_queue_paused)
        self.assertLessEqual(self.orchestrator.max_clients, 3)

    async def test_critical_state_freezes_noncritical_operations(self):
        for _ in range(11):
            self.orchestrator._record_event("flood_wait")

        decision = await self.autopilot.run_once()
        metrics = self.orchestrator.get_runtime_metrics()

        self.assertEqual(decision.state, SystemState.CRITICAL)
        self.assertEqual(metrics["client_limit"], 1)
        self.assertTrue(metrics["noncritical_frozen"])

    async def test_more_than_ten_percent_error_accounts_degrades_system(self):
        session = self.session_factory()
        for account_id in (1, 2):
            account = session.get(AdvertisingAccount, account_id)
            account.orchestration_state = AccountState.ERROR.value
        session.commit()
        session.close()

        decision = await self.autopilot.run_once()
        session = self.session_factory()
        frozen = session.get(AdvertisingAccount, 1)

        self.assertEqual(decision.state, SystemState.DEGRADED)
        self.assertIsNotNone(frozen.autopilot_frozen_until)
        session.close()

    async def test_proxy_failure_ratio_pauses_pool(self):
        session = self.session_factory()
        for account_id in range(1, 6):
            account = session.get(AdvertisingAccount, account_id)
            account.proxy_enabled = True
            account.proxy_status = "failed" if account_id <= 2 else "working"
        session.commit()
        session.close()

        decision = await self.autopilot.run_once()

        self.assertEqual(decision.state, SystemState.DEGRADED)
        self.assertTrue(decision.pause_proxy_pool)
        self.assertTrue(self.orchestrator.proxy_pool_paused)

    async def test_unstable_proxy_is_disabled_with_cooldown(self):
        session = self.session_factory()
        endpoint = ProxyEndpoint(
            proxy_type="SOCKS5",
            host="proxy.example",
            port=1080,
            status="failed",
            enabled=True,
            score=25,
            success_count=1,
            failure_count=3,
        )
        session.add(endpoint)
        session.commit()
        endpoint_id = endpoint.id
        session.close()

        await self.autopilot.run_once()
        session = self.session_factory()
        endpoint = session.get(ProxyEndpoint, endpoint_id)

        self.assertFalse(endpoint.enabled)
        self.assertIsNotNone(endpoint.disabled_until)
        session.close()

    async def test_stable_recovery_resumes_queue_and_concurrency(self):
        for _ in range(6):
            self.orchestrator._record_event("flood_wait")
        await self.autopilot.run_once()
        self.assertTrue(self.orchestrator.login_queue_paused)

        self.orchestrator._events.clear()
        first = await self.autopilot.run_once()
        second = await self.autopilot.run_once()
        third = await self.autopilot.run_once()

        self.assertEqual(first.state, SystemState.RECOVERY)
        self.assertEqual(second.state, SystemState.RECOVERY)
        self.assertEqual(third.state, SystemState.HEALTHY)
        self.assertFalse(self.orchestrator.login_queue_paused)
        self.assertEqual(self.orchestrator.max_clients, 5)

    async def test_engine_lifecycle_is_non_blocking(self):
        self.assertTrue(await self.autopilot.start())
        await asyncio.sleep(0)
        self.assertTrue(self.autopilot.running)
        await self.autopilot.stop()
        self.assertFalse(self.autopilot.running)


if __name__ == "__main__":
    unittest.main()
