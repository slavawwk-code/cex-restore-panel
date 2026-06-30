import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.config import load_settings
from app.database import get_session
from app.database.models import (
    AdvertisingAccount,
    AutopilotControlState,
    ProxyEndpoint,
)
from app.services.account_orchestrator import (
    AccountOrchestrator,
    AccountState,
    OrchestratorError,
    account_orchestrator,
)

logger = logging.getLogger(__name__)


class SystemState(StrEnum):
    HEALTHY = "HEALTHY"
    LOAD_HIGH = "LOAD_HIGH"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True)
class AutopilotMetrics:
    total_accounts: int
    error_accounts: int
    degraded_accounts: int
    reauth_accounts: int
    configured_proxies: int
    failed_proxies: int
    unavailable_endpoints: int
    average_proxy_latency_ms: int | None
    flood_waits_1m: int
    connection_errors_1m: int
    timeouts_1m: int
    login_queue_size: int
    active_tasks: int
    connected_clients: int
    client_limit: int

    @property
    def account_error_ratio(self) -> float:
        return self.error_accounts / self.total_accounts if self.total_accounts else 0.0

    @property
    def proxy_failure_ratio(self) -> float:
        return self.failed_proxies / self.configured_proxies if self.configured_proxies else 0.0


@dataclass(frozen=True)
class AutopilotDecision:
    state: SystemState
    client_limit: int
    pause_logins: bool
    pause_proxy_pool: bool
    freeze_noncritical: bool
    reasons: tuple[str, ...]


class AutopilotEngine:
    """Low-overhead policy loop controlling AccountOrchestrator, never Telethon."""

    def __init__(
        self,
        orchestrator: AccountOrchestrator = account_orchestrator,
        *,
        interval_seconds: int | None = None,
        queue_threshold: int | None = None,
        recovery_cooldown_seconds: int | None = None,
        healthy_clients: int | None = None,
        session_factory=get_session,
    ) -> None:
        settings = load_settings(require_secrets=False)
        self.orchestrator = orchestrator
        self.interval_seconds = interval_seconds or settings.autopilot_interval_seconds
        self.queue_threshold = queue_threshold or settings.autopilot_queue_threshold
        self.recovery_cooldown_seconds = (
            recovery_cooldown_seconds
            or settings.autopilot_recovery_cooldown_seconds
        )
        self.healthy_clients = healthy_clients or settings.autopilot_healthy_clients
        if not 10 <= self.interval_seconds <= 30:
            raise ValueError("Autopilot interval must be between 10 and 30 seconds")
        if not 5 <= self.healthy_clients <= 10:
            raise ValueError("healthy_clients must be between 5 and 10")
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None
        self._state = SystemState.HEALTHY
        self._stable_cycles = 0
        self._account_retry_at: dict[int, datetime] = {}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def state(self) -> SystemState:
        return self._state

    def forget_account(self, account_id: int) -> None:
        """Drop per-account retry/cooldown memory after lifecycle reset/delete."""
        self._account_retry_at.pop(account_id, None)

    async def start(self) -> bool:
        if self.running:
            return True
        self._task = asyncio.create_task(self._run(), name="autopilot-engine")
        logger.info(
            "autopilot_started system_state=%s interval_seconds=%s",
            self._state.value,
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
        logger.info("autopilot_stopped system_state=%s", self._state.value)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                await self.run_once()
            except Exception:
                logger.exception(
                    "autopilot_cycle_failed system_state=%s action_taken=none",
                    self._state.value,
                )

    async def run_once(self) -> AutopilotDecision:
        metrics = self.collect_metrics()
        decision = self._decide(metrics)
        await self._apply_decision(decision)
        affected_proxies = self._manage_proxy_pool(metrics)
        affected_accounts = await self._self_heal(metrics, decision)
        self._persist_snapshot(
            decision,
            affected_accounts=affected_accounts,
            affected_proxies=affected_proxies,
        )
        self._state = decision.state
        logger.info(
            "autopilot_decision system_state=%s action_taken=%s reason=%s "
            "affected_accounts=%s affected_proxies=%s",
            decision.state.value,
            self._action_label(decision),
            "; ".join(decision.reasons) or "stable",
            affected_accounts,
            affected_proxies,
        )
        return decision

    def collect_metrics(self) -> AutopilotMetrics:
        runtime = self.orchestrator.get_runtime_metrics(window_seconds=60)
        events = runtime["event_counts"]
        session = self._session_factory()
        try:
            accounts = session.query(AdvertisingAccount).all()
            configured = [account for account in accounts if account.proxy_enabled]
            failed = [
                account for account in configured if account.proxy_status == "failed"
            ]
            latencies = [
                account.proxy_latency_ms
                for account in configured
                if account.proxy_latency_ms is not None
            ]
            unavailable_endpoints = (
                session.query(ProxyEndpoint)
                .filter(
                    (ProxyEndpoint.enabled.is_(False))
                    | (ProxyEndpoint.status == "failed")
                )
                .count()
            )
            return AutopilotMetrics(
                total_accounts=len(accounts),
                error_accounts=sum(
                    account.orchestration_state == AccountState.ERROR.value
                    for account in accounts
                ),
                degraded_accounts=sum(
                    account.orchestration_state == AccountState.DEGRADED.value
                    for account in accounts
                ),
                reauth_accounts=sum(
                    account.orchestration_state == AccountState.REAUTH_REQUIRED.value
                    for account in accounts
                ),
                configured_proxies=len(configured),
                failed_proxies=len(failed),
                unavailable_endpoints=unavailable_endpoints,
                average_proxy_latency_ms=(
                    round(sum(latencies) / len(latencies)) if latencies else None
                ),
                flood_waits_1m=events.get("flood_wait", 0),
                connection_errors_1m=events.get("connection_error", 0),
                timeouts_1m=events.get("timeout", 0),
                login_queue_size=runtime["login_queue_size"],
                active_tasks=runtime["active_tasks"],
                connected_clients=runtime["connected_clients"],
                client_limit=runtime["client_limit"],
            )
        finally:
            session.close()

    def _decide(self, metrics: AutopilotMetrics) -> AutopilotDecision:
        reasons: list[str] = []
        if metrics.flood_waits_1m > 5:
            reasons.append(f"FloodWait за минуту: {metrics.flood_waits_1m}")
        if metrics.account_error_ratio > 0.10:
            reasons.append(
                f"аккаунты ERROR: {metrics.account_error_ratio:.0%}"
            )
        if metrics.proxy_failure_ratio > 0.30:
            reasons.append(
                f"ошибки прокси: {metrics.proxy_failure_ratio:.0%}"
            )
        if metrics.login_queue_size > self.queue_threshold:
            reasons.append(f"очередь login: {metrics.login_queue_size}")
        if metrics.average_proxy_latency_ms and metrics.average_proxy_latency_ms > 2000:
            reasons.append(
                f"средняя задержка прокси: {metrics.average_proxy_latency_ms} ms"
            )

        critical = (
            metrics.flood_waits_1m > 10
            or metrics.account_error_ratio > 0.30
            or metrics.proxy_failure_ratio > 0.60
        )
        degraded = (
            metrics.flood_waits_1m > 5
            or metrics.account_error_ratio > 0.10
            or metrics.proxy_failure_ratio > 0.30
            or metrics.connection_errors_1m + metrics.timeouts_1m > 10
        )
        load_high = metrics.login_queue_size > self.queue_threshold or (
            metrics.active_tasks >= metrics.client_limit
            and metrics.login_queue_size > 0
        )

        if critical:
            state = SystemState.CRITICAL
            self._stable_cycles = 0
        elif degraded:
            state = SystemState.DEGRADED
            self._stable_cycles = 0
        elif load_high:
            state = SystemState.LOAD_HIGH
            self._stable_cycles = 0
        elif self._state != SystemState.HEALTHY and self._stable_cycles < 2:
            self._stable_cycles += 1
            state = SystemState.RECOVERY
            reasons.append("стабилизация после защитного режима")
        else:
            self._stable_cycles = 0
            state = SystemState.HEALTHY

        client_limits = {
            SystemState.HEALTHY: self.healthy_clients,
            SystemState.LOAD_HIGH: min(5, max(3, self.healthy_clients - 2)),
            SystemState.DEGRADED: min(3, max(1, self.healthy_clients // 2)),
            SystemState.CRITICAL: 1,
            SystemState.RECOVERY: min(3, self.healthy_clients),
        }
        return AutopilotDecision(
            state=state,
            client_limit=client_limits[state],
            pause_logins=metrics.flood_waits_1m > 5 or state == SystemState.CRITICAL,
            pause_proxy_pool=metrics.proxy_failure_ratio > 0.30,
            freeze_noncritical=state == SystemState.CRITICAL,
            reasons=tuple(reasons),
        )

    async def _apply_decision(self, decision: AutopilotDecision) -> None:
        await self.orchestrator.set_client_limit(decision.client_limit)
        if decision.pause_logins:
            self.orchestrator.pause_login_queue()
        else:
            self.orchestrator.resume_login_queue()
        self.orchestrator.set_proxy_pool_paused(decision.pause_proxy_pool)
        self.orchestrator.freeze_noncritical_operations(
            decision.freeze_noncritical
        )

    def _manage_proxy_pool(self, metrics: AutopilotMetrics) -> int:
        now = datetime.now(UTC).replace(tzinfo=None)
        disabled_until = now + timedelta(seconds=self.recovery_cooldown_seconds)
        changed = 0
        session = self._session_factory()
        try:
            endpoints = session.query(ProxyEndpoint).all()
            for endpoint in endpoints:
                total = (endpoint.success_count or 0) + (endpoint.failure_count or 0)
                failure_rate = (
                    (endpoint.failure_count or 0) / total if total else 0.0
                )
                unstable = total >= 3 and (
                    failure_rate > 0.30 or (endpoint.score or 0) < 50
                )
                if unstable and endpoint.enabled:
                    endpoint.enabled = False
                    endpoint.disabled_until = disabled_until
                    endpoint.status = "failed"
                    changed += 1
                elif (
                    not endpoint.enabled
                    and endpoint.disabled_until
                    and endpoint.disabled_until <= now
                ):
                    endpoint.enabled = True
                    endpoint.disabled_until = None
                    endpoint.status = "unknown"
                    changed += 1
            session.commit()
        finally:
            session.close()
        return changed

    async def _self_heal(
        self,
        metrics: AutopilotMetrics,
        decision: AutopilotDecision,
    ) -> int:
        if decision.state in {SystemState.CRITICAL, SystemState.DEGRADED}:
            return self._freeze_problem_accounts()

        now = datetime.now(UTC).replace(tzinfo=None)
        session = self._session_factory()
        try:
            candidates = (
                session.query(AdvertisingAccount)
                .filter(
                    AdvertisingAccount.orchestration_state.in_(
                        [AccountState.ERROR.value, AccountState.DEGRADED.value]
                    )
                )
                .order_by(AdvertisingAccount.orchestration_updated_at.asc())
                .limit(3)
                .all()
            )
            candidate_data = [
                (account.id, account.proxy_enabled, account.proxy_status)
                for account in candidates
                if self._account_retry_at.get(account.id, now) <= now
                and (
                    account.autopilot_frozen_until is None
                    or account.autopilot_frozen_until <= now
                )
            ]
        finally:
            session.close()

        healed = 0
        for account_id, proxy_enabled, proxy_status in candidate_data:
            self._account_retry_at[account_id] = now + timedelta(
                seconds=self.recovery_cooldown_seconds
            )
            try:
                self.orchestrator.unfreeze_account(account_id)
                if (
                    proxy_enabled
                    and proxy_status == "failed"
                    and not decision.pause_proxy_pool
                ):
                    with suppress(OrchestratorError):
                        await self.orchestrator.allocate_proxy(account_id)
                result = await self.orchestrator.restart_account_session(account_id)
                if result.get("connected"):
                    healed += 1
            except Exception:
                logger.warning(
                    "autopilot_recovery_failed account_id=%s action_taken=retry_later",
                    account_id,
                    exc_info=True,
                )
        return healed

    def _freeze_problem_accounts(self) -> int:
        now = datetime.now(UTC).replace(tzinfo=None)
        until = now + timedelta(seconds=self.recovery_cooldown_seconds)
        session = self._session_factory()
        try:
            account_ids = [
                item[0]
                for item in (
                    session.query(AdvertisingAccount.id)
                    .filter(
                        AdvertisingAccount.orchestration_state.in_(
                            [AccountState.ERROR.value, AccountState.DEGRADED.value]
                        ),
                        (
                            (AdvertisingAccount.autopilot_frozen_until.is_(None))
                            | (AdvertisingAccount.autopilot_frozen_until <= now)
                        ),
                    )
                    .limit(10)
                    .all()
                )
            ]
        finally:
            session.close()
        for account_id in account_ids:
            self.orchestrator.freeze_account(
                account_id,
                until,
                "Autopilot cooldown после повторяющихся ошибок",
            )
            self._account_retry_at[account_id] = until
        return len(account_ids)

    def _persist_snapshot(
        self,
        decision: AutopilotDecision,
        *,
        affected_accounts: int,
        affected_proxies: int,
    ) -> None:
        session = self._session_factory()
        try:
            snapshot = session.get(AutopilotControlState, 1)
            if snapshot is None:
                snapshot = AutopilotControlState(id=1)
                session.add(snapshot)
            snapshot.system_state = decision.state.value
            snapshot.action_taken = self._action_label(decision)
            snapshot.reason = "; ".join(decision.reasons) or "stable"
            snapshot.affected_accounts = affected_accounts
            snapshot.affected_proxies = affected_proxies
            snapshot.client_limit = decision.client_limit
            snapshot.login_queue_paused = decision.pause_logins
            snapshot.proxy_pool_paused = decision.pause_proxy_pool
            snapshot.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        finally:
            session.close()

    @staticmethod
    def _action_label(decision: AutopilotDecision) -> str:
        actions = [f"clients={decision.client_limit}"]
        if decision.pause_logins:
            actions.append("pause_logins")
        if decision.pause_proxy_pool:
            actions.append("pause_proxy_pool")
        if decision.freeze_noncritical:
            actions.append("freeze_noncritical")
        return ",".join(actions)


autopilot_engine = AutopilotEngine()
