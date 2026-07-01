import asyncio
import hashlib
import inspect
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Awaitable, Callable

from sqlalchemy import func
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
    RPCError,
    SessionPasswordNeededError,
    UnauthorizedError,
)

from app.config import load_settings
from app.database import get_session
from app.database.models import AdvertisingAccount, ProxyEndpoint
from app.services.account_health import update_persisted_health
from app.services.auth_guard import AuthGuard, AuthGuardError
from app.services.account_sessions import (
    AccountSessionError,
    create_account_client,
    finalize_login_session,
    import_session_bytes,
    resolve_session_source,
    save_string_session,
)
from app.services.proxy import (
    ParsedProxy,
    ProxyDetectionResult,
    configure_proxy,
    detect_working_proxy_type,
    disable_proxy,
    run_fast_proxy_check,
    run_full_proxy_diagnostics,
    save_detected_proxy,
)
from app.services.telethon_auth import (
    TelethonAuthError,
    check_session_status,
    disconnect_session,
)
from app.telethon.client import TelethonClientManager

logger = logging.getLogger(__name__)


class AccountState(StrEnum):
    CREATED = "CREATED"
    AUTHENTICATING = "AUTHENTICATING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"


class AuthFlowState(StrEnum):
    CREATED = "CREATED"
    CODE_SENT = "CODE_SENT"
    CODE_VERIFIED = "CODE_VERIFIED"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


class OrchestratorError(RuntimeError):
    """Safe orchestration failure that can be shown to an operator."""


@dataclass(frozen=True)
class OperationEvent:
    timestamp: float
    event_type: str
    account_id: int | None
    proxy_id: int | None


class AdaptiveConcurrencyLimiter:
    """Async limiter whose capacity can be changed without cancelling work."""

    def __init__(self, limit: int):
        self._limit = limit
        self._active = 0
        self._condition = asyncio.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    async def set_limit(self, limit: int) -> None:
        if not 1 <= limit <= 10:
            raise ValueError("client limit must be between 1 and 10")
        async with self._condition:
            self._limit = limit
            self._condition.notify_all()

    async def __aenter__(self):
        async with self._condition:
            await self._condition.wait_for(lambda: self._active < self._limit)
            self._active += 1
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        async with self._condition:
            self._active -= 1
            self._condition.notify_all()


@dataclass(repr=False)
class _LoginJob:
    account_id: int
    action: str
    code: str | None = field(default=None, repr=False)
    phone_code_hash: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    auth_generation: int = field(default=0, repr=False)
    future: asyncio.Future = field(repr=False, default=None)


@dataclass(repr=False)
class AuthContext:
    """Persistent Telethon auth transaction for one account."""

    account_id: int
    client: Any = field(repr=False)
    phone: str
    auth_generation: int
    state: AuthFlowState = AuthFlowState.CREATED
    phone_code_hash: str | None = field(default=None, repr=False)
    session_fingerprint: str = ""
    password_attempts: int = field(default=0, repr=False)
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float = 0.0
    updated_at: float = field(default_factory=time.monotonic)

    @property
    def context_id(self) -> str:
        return f"{self.account_id}:{id(self.client):x}:{self.auth_generation}"

    def touch(self, state: AuthFlowState | None = None) -> None:
        if state is not None:
            self.state = state
        self.updated_at = time.monotonic()


class AccountOrchestrator:
    """Central concurrency, state, proxy, session, and rate-limit controller."""

    def __init__(
        self,
        *,
        max_clients: int | None = None,
        login_concurrency: int | None = None,
        health_batch_size: int | None = None,
        global_delay_seconds: float | None = None,
        account_delay_seconds: float | None = None,
        login_max_retries: int | None = None,
        session_factory: Callable = get_session,
        client_manager: TelethonClientManager | None = None,
    ) -> None:
        settings = load_settings(require_secrets=False)
        self.max_clients = max_clients or settings.orchestrator_max_clients
        self.login_concurrency = (
            login_concurrency or settings.orchestrator_login_concurrency
        )
        self.health_batch_size = (
            health_batch_size or settings.orchestrator_health_batch_size
        )
        self.global_delay_seconds = (
            settings.orchestrator_global_delay_seconds
            if global_delay_seconds is None
            else global_delay_seconds
        )
        self.account_delay_seconds = (
            settings.orchestrator_account_delay_seconds
            if account_delay_seconds is None
            else account_delay_seconds
        )
        self.login_max_retries = (
            login_max_retries or settings.orchestrator_login_max_retries
        )
        if not 1 <= self.max_clients <= 10:
            raise ValueError("max_clients must be between 1 and 10")
        if not 2 <= self.login_concurrency <= 5:
            raise ValueError("login_concurrency must be between 2 and 5")
        if not 3 <= self.health_batch_size <= 5:
            raise ValueError("health_batch_size must be between 3 and 5")

        self._session_factory = session_factory
        self.client_manager = client_manager or TelethonClientManager()
        self._client_slots = AdaptiveConcurrencyLimiter(self.max_clients)
        self._account_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_rate_lock = asyncio.Lock()
        self._next_global_at = 0.0
        self._next_account_at: dict[int, float] = {}
        self._login_queue: asyncio.Queue[_LoginJob | None] = asyncio.Queue()
        self._login_workers: list[asyncio.Task] = []
        self._login_resume_event = asyncio.Event()
        self._login_resume_event.set()
        self._proxy_pool_paused = False
        self._noncritical_frozen = False
        self._events: deque[OperationEvent] = deque(maxlen=5000)
        self._account_operations: defaultdict[int, int] = defaultdict(int)
        self._queued_login_accounts: defaultdict[int, int] = defaultdict(int)
        self._blocked_accounts: set[int] = set()
        self._disabled_accounts: set[int] = set()
        self.auth_guard = AuthGuard()
        self._auth_contexts: dict[int, AuthContext] = self.auth_guard.contexts
        self._started = False

    @property
    def running(self) -> bool:
        return self._started and all(not task.done() for task in self._login_workers)

    @property
    def login_queue_size(self) -> int:
        return self._login_queue.qsize()

    @property
    def login_queue_paused(self) -> bool:
        return not self._login_resume_event.is_set()

    @property
    def proxy_pool_paused(self) -> bool:
        return self._proxy_pool_paused

    async def set_client_limit(self, limit: int) -> None:
        await self._client_slots.set_limit(limit)
        self.max_clients = limit

    def pause_login_queue(self) -> None:
        self._login_resume_event.clear()

    def resume_login_queue(self) -> None:
        self._login_resume_event.set()

    def set_proxy_pool_paused(self, paused: bool) -> None:
        self._proxy_pool_paused = paused

    def freeze_noncritical_operations(self, frozen: bool) -> None:
        self._noncritical_frozen = frozen

    def get_runtime_metrics(self, window_seconds: int = 60) -> dict:
        cutoff = time.monotonic() - window_seconds
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()
        counts: dict[str, int] = defaultdict(int)
        for event in self._events:
            counts[event.event_type] += 1
        return {
            "event_counts": dict(counts),
            "login_queue_size": self.login_queue_size,
            "login_queue_paused": self.login_queue_paused,
            "active_tasks": self._client_slots.active,
            "client_limit": self._client_slots.limit,
            "connected_clients": len(self.client_manager.clients),
            "active_auth_contexts": len(self._auth_contexts),
            "proxy_pool_paused": self._proxy_pool_paused,
            "noncritical_frozen": self._noncritical_frozen,
        }

    def is_account_busy(self, account_id: int) -> bool:
        return bool(
            self._account_operations.get(account_id, 0)
            or self._queued_login_accounts.get(account_id, 0)
        )

    async def prepare_account_removal(
        self,
        account_id: int,
        *,
        force: bool = False,
        timeout_seconds: float = 30,
    ) -> None:
        """Block new work and gracefully drain one account before hard delete."""
        if self.is_account_busy(account_id) and not force:
            raise OrchestratorError("Аккаунт выполняет операции; удаление заблокировано")
        self._blocked_accounts.add(account_id)
        self._disabled_accounts.add(account_id)
        self.cancel_queued_login(account_id, "Аккаунт подготовлен к удалению")
        await self._drop_auth_context(account_id, "account_removal")
        lock = self._account_locks[account_id]
        acquired = False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout_seconds)
            acquired = True
            await self.client_manager.disconnect_client(account_id)
        except Exception:
            self._blocked_accounts.discard(account_id)
            self._disabled_accounts.discard(account_id)
            raise
        finally:
            if acquired:
                lock.release()

    async def disable_runtime_account(self, account_id: int) -> None:
        """Stop queued/future sending while retaining DB and session state."""
        self._disabled_accounts.add(account_id)
        self.cancel_queued_login(account_id, "Аккаунт отключён")
        await self._drop_auth_context(account_id, "account_disabled")
        lock = self._account_locks[account_id]
        try:
            async with lock:
                await self.client_manager.disconnect_client(account_id)
        except Exception:
            self._disabled_accounts.discard(account_id)
            raise

    async def prepare_account_reauth(self, account_id: int) -> None:
        """Drain runtime work and disconnect without deleting session storage."""
        self._disabled_accounts.add(account_id)
        self._blocked_accounts.add(account_id)
        self.cancel_queued_login(account_id, "Авторизация аккаунта сброшена")
        await self._drop_auth_context(account_id, "account_reauth")
        lock = self._account_locks[account_id]
        try:
            async with lock:
                await self.client_manager.disconnect_client(account_id)
        except Exception:
            self._blocked_accounts.discard(account_id)
            self._disabled_accounts.discard(account_id)
            raise
        self._next_account_at.pop(account_id, None)

    def activate_account_for_reauth(self, account_id: int) -> None:
        self._disabled_accounts.discard(account_id)
        self._blocked_accounts.discard(account_id)
        self._next_account_at.pop(account_id, None)

    def enable_runtime_account(self, account_id: int) -> None:
        """Return a previously soft-disabled account to runtime scheduling."""
        self.activate_account_for_reauth(account_id)

    def abort_account_removal(self, account_id: int) -> None:
        self._blocked_accounts.discard(account_id)
        self._disabled_accounts.discard(account_id)

    def forget_account(self, account_id: int) -> None:
        """Remove all non-persistent runtime registry entries for a deleted account."""
        self.cancel_queued_login(account_id, "Аккаунт удалён")
        context = self.auth_guard.reset_account(account_id)
        if context is not None:
            try:
                asyncio.get_running_loop().create_task(context.client.disconnect())
            except RuntimeError:
                pass
        self._account_operations.pop(account_id, None)
        self._queued_login_accounts.pop(account_id, None)
        self._next_account_at.pop(account_id, None)
        self._blocked_accounts.discard(account_id)
        self._disabled_accounts.discard(account_id)
        self._account_locks.pop(account_id, None)
        self._events = deque(
            (event for event in self._events if event.account_id != account_id),
            maxlen=5000,
        )

    def cancel_queued_login(self, account_id: int, reason: str) -> int:
        """Remove queued login jobs without interrupting an already-running step."""
        retained: list[_LoginJob | None] = []
        cancelled = 0
        while True:
            try:
                job = self._login_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._login_queue.task_done()
            if job is not None and job.account_id == account_id:
                cancelled += 1
                self._decrement_queued_login(account_id)
                job.code = None
                job.phone_code_hash = None
                job.password = None
                if not job.future.done():
                    job.future.set_exception(OrchestratorError(reason))
            else:
                retained.append(job)
        for job in retained:
            self._login_queue.put_nowait(job)
        return cancelled

    @asynccontextmanager
    async def _account_operation(self, account_id: int, *, client_slot: bool = True):
        self._account_operations[account_id] += 1
        try:
            async with self._account_locks[account_id]:
                if account_id in self._blocked_accounts:
                    raise OrchestratorError("Аккаунт удаляется и недоступен для операций")
                if client_slot:
                    async with self._client_slots:
                        yield
                else:
                    yield
        finally:
            self._account_operations[account_id] -= 1
            if self._account_operations[account_id] <= 0:
                self._account_operations.pop(account_id, None)

    async def start(self) -> None:
        if self.running:
            return
        self._started = True
        self._login_workers = [
            asyncio.create_task(self._login_worker(index), name=f"account-login-{index}")
            for index in range(self.login_concurrency)
        ]
        logger.info(
            "orchestrator_started max_clients=%s login_workers=%s health_batch=%s",
            self.max_clients,
            self.login_concurrency,
            self.health_batch_size,
        )

    async def stop(self) -> None:
        if not self._started:
            await self.client_manager.disconnect_all()
            return
        # Do not execute a backlog of new login attempts during shutdown.
        while True:
            try:
                queued = self._login_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if queued is not None:
                self._decrement_queued_login(queued.account_id)
                queued.code = None
                queued.phone_code_hash = None
                queued.password = None
                if not queued.future.done():
                    queued.future.set_exception(
                        OrchestratorError("Сервис завершает работу")
                    )
            self._login_queue.task_done()
        for _ in self._login_workers:
            await self._login_queue.put(None)
        self._login_resume_event.set()
        await self._login_queue.join()
        for task in self._login_workers:
            with suppress(asyncio.CancelledError):
                await task
        self._login_workers.clear()
        self._started = False
        await self._drop_all_auth_contexts("orchestrator_stop")
        await self.client_manager.disconnect_all()
        logger.info("orchestrator_stopped")

    async def login_account(
        self,
        account_id: int,
        *,
        action: str = "request_code",
        code: str | None = None,
        phone_code_hash: str | None = None,
        password: str | None = None,
        force_reset: bool = False,
    ) -> dict:
        """Queue one phone login step; secrets are never included in logs/repr."""
        if action not in {"request_code", "code", "password"}:
            raise OrchestratorError("Неизвестный этап авторизации")
        if account_id in self._blocked_accounts:
            raise OrchestratorError("Аккаунт удаляется и недоступен для авторизации")
        await self._expire_auth_context_if_needed(account_id)
        session = self._session_factory()
        try:
            account = self._require_account(session, account_id)
            auth_generation = account.auth_generation or 0
            try:
                self.auth_guard.begin_auth_operation(
                    account_id,
                    action,
                    force_reset=force_reset,
                )
            except AuthGuardError as error:
                raise self._auth_guard_to_orchestrator_error(error) from error
        finally:
            session.close()
        await self.start()
        future = asyncio.get_running_loop().create_future()
        self._queued_login_accounts[account_id] += 1
        try:
            await self._login_queue.put(
                _LoginJob(
                    account_id,
                    action,
                    code,
                    phone_code_hash,
                    password,
                    auth_generation,
                    future,
                )
            )
            return await future
        finally:
            self.auth_guard.finish_auth_operation(account_id)

    async def import_session(
        self,
        account_id: int,
        filename: str,
        payload: bytes,
    ) -> dict:
        async with self._account_operation(account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                await self._ensure_auth_mutation_allowed(
                    session,
                    account,
                    "import_session",
                )
                self._set_state(session, account, AccountState.AUTHENTICATING)
                await self.client_manager.disconnect_client(account_id)
                await self._ensure_proxy_ready(session, account)
                result = await import_session_bytes(session, account, filename, payload)
                self._set_state(session, account, AccountState.ACTIVE)
                self._log(account, "import_session", "success", started)
                return result
            except Exception as error:
                self._safe_state_after_error(session, account_id, error)
                self._log_id(account_id, None, "import_session", "error", started)
                raise
            finally:
                session.close()

    async def import_string_session(self, account_id: int, value: str) -> dict:
        async with self._account_operation(account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                await self._ensure_auth_mutation_allowed(
                    session,
                    account,
                    "import_string_session",
                )
                self._set_state(session, account, AccountState.AUTHENTICATING)
                await self.client_manager.disconnect_client(account_id)
                await self._ensure_proxy_ready(session, account)
                result = await save_string_session(session, account, value)
                self._set_state(session, account, AccountState.ACTIVE)
                self._log(account, "import_string_session", "success", started)
                return result
            except Exception as error:
                self._safe_state_after_error(session, account_id, error)
                self._log_id(account_id, None, "import_string_session", "error", started)
                raise
            finally:
                session.close()

    async def assign_proxy(
        self,
        account_id: int,
        proxy_id: int | None = None,
        *,
        proxy_config: ParsedProxy | None = None,
        validate: bool = True,
    ) -> ProxyDetectionResult | None:
        """Assign a registry/config proxy, validating it before active use."""
        async with self._account_operation(account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                await self._ensure_auth_mutation_allowed(
                    session,
                    account,
                    "assign_proxy",
                )
                endpoint = None
                if proxy_config is None:
                    if proxy_id is None:
                        raise OrchestratorError("Не указан прокси для назначения")
                    endpoint = session.get(ProxyEndpoint, proxy_id)
                    if not endpoint or not endpoint.enabled:
                        raise OrchestratorError("Прокси не найден или отключён")
                    proxy_config = self._config_from_endpoint(endpoint)

                detection = None
                if validate:
                    await self._throttle(account_id)
                    detection = await detect_working_proxy_type(
                        proxy_config,
                        candidate_types=proxy_config.candidate_types,
                    )
                    if not detection.success:
                        if endpoint:
                            self._update_endpoint(endpoint, detection)
                            session.commit()
                        self._set_state(
                            session,
                            account,
                            AccountState.DEGRADED,
                            "Прокси не прошёл проверку Telegram",
                        )
                        self._log(account, "assign_proxy", "failed", started)
                        return detection
                    save_detected_proxy(session, account, proxy_config, detection)
                else:
                    configure_proxy(
                        session,
                        account,
                        proxy_config.proxy_type,
                        proxy_config.host,
                        proxy_config.port,
                        proxy_config.username,
                        proxy_config.password,
                    )

                endpoint = endpoint or self._find_or_create_endpoint(
                    session, proxy_config, detection
                )
                account.proxy_id = endpoint.id
                session.commit()
                await self.client_manager.disconnect_client(account_id)
                self._log(account, "assign_proxy", "success", started)
                return detection
            finally:
                session.close()

    async def allocate_proxy(self, account_id: int) -> ProxyDetectionResult | None:
        """Choose the least-used healthy endpoint within its capacity."""
        if self._proxy_pool_paused:
            raise OrchestratorError("Пул прокси временно приостановлен Autopilot")
        session = self._session_factory()
        try:
            usage = (
                session.query(
                    ProxyEndpoint,
                    func.count(AdvertisingAccount.id).label("account_count"),
                )
                .outerjoin(
                    AdvertisingAccount,
                    AdvertisingAccount.proxy_id == ProxyEndpoint.id,
                )
                .filter(
                    ProxyEndpoint.enabled.is_(True),
                    ProxyEndpoint.status == "working",
                    (
                        (ProxyEndpoint.disabled_until.is_(None))
                        | (ProxyEndpoint.disabled_until <= datetime.now(UTC).replace(tzinfo=None))
                    ),
                )
                .group_by(ProxyEndpoint.id)
                .order_by(
                    func.count(AdvertisingAccount.id).asc(),
                    ProxyEndpoint.latency_ms.asc(),
                )
                .all()
            )
            endpoint_id = next(
                (
                    endpoint.id
                    for endpoint, count in usage
                    if count < endpoint.max_accounts
                ),
                None,
            )
        finally:
            session.close()
        if endpoint_id is None:
            raise OrchestratorError("Нет доступных проверенных прокси")
        return await self.assign_proxy(account_id, endpoint_id)

    async def check_proxy(
        self, account_id: int, *, full: bool = False
    ) -> Any:
        async with self._account_operation(account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                await self._throttle(account_id)
                result = (
                    await run_full_proxy_diagnostics(session, account)
                    if full
                    else await run_fast_proxy_check(session, account)
                )
                self._sync_endpoint_from_account(session, account)
                if not result.success:
                    self._record_event("proxy_failure", account)
                    self._set_state(
                        session,
                        account,
                        AccountState.DEGRADED,
                        account.proxy_last_error,
                    )
                elif account.session_connected:
                    self._set_state(session, account, AccountState.ACTIVE)
                self._log(
                    account,
                    "proxy_diagnostics" if full else "proxy_fast_check",
                    "success" if result.success else "failed",
                    started,
                )
                return result
            finally:
                session.close()

    async def disable_account_proxy(self, account_id: int) -> None:
        async with self._account_operation(account_id, client_slot=False):
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                await self._ensure_auth_mutation_allowed(
                    session,
                    account,
                    "disable_proxy",
                )
                disable_proxy(session, account)
                await self.client_manager.disconnect_client(account_id)
            finally:
                session.close()

    async def validate_account(self, account_id: int) -> dict:
        """Validate proxy/session serially for one account and refresh health."""
        async with self._account_operation(account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                proxy_result = None
                if account.proxy_enabled:
                    if not account.proxy_type:
                        self._set_state(
                            session,
                            account,
                            AccountState.DEGRADED,
                            "Тип прокси не определён",
                        )
                    else:
                        await self._throttle(account_id)
                        proxy_result = await run_fast_proxy_check(session, account)
                        self._sync_endpoint_from_account(session, account)
                        if not proxy_result.success:
                            self._record_event("proxy_failure", account)

                resolution = resolve_session_source(account)
                if resolution is None:
                    self._set_state(
                        session,
                        account,
                        AccountState.REAUTH_REQUIRED,
                        "Telegram-сессия не настроена",
                    )
                    update_persisted_health(session, account)
                    session.commit()
                    return {"connected": False, "reason": "Сессия не настроена"}

                await self._throttle(account_id)
                auth_result = await check_session_status(session, account)
                if not auth_result["connected"]:
                    reason_text = str(auth_result.get("reason", "")).lower()
                    if "timeout" in reason_text or "тайм" in reason_text:
                        self._record_event("timeout", account)
                    elif "connection" in reason_text or "подключ" in reason_text:
                        self._record_event("connection_error", account)
                if auth_result["connected"] and (
                    not account.proxy_enabled or (proxy_result and proxy_result.success)
                ):
                    self._set_state(session, account, AccountState.ACTIVE)
                elif auth_result["connected"]:
                    self._set_state(
                        session,
                        account,
                        AccountState.DEGRADED,
                        account.proxy_last_error or "Прокси недоступен",
                    )
                else:
                    self._set_state(
                        session,
                        account,
                        AccountState.REAUTH_REQUIRED,
                        auth_result.get("reason"),
                    )
                self._log(account, "validate_account", "complete", started)
                return {
                    **auth_result,
                    "proxy": proxy_result,
                    "state": account.orchestration_state,
                }
            except Exception as error:
                self._safe_state_after_error(session, account_id, error)
                self._log_id(account_id, None, "validate_account", "error", started)
                return {"connected": False, "reason": type(error).__name__}
            finally:
                session.close()

    async def run_health_cycle(self) -> dict[int, dict]:
        """Validate 100+ accounts in bounded batches without blocking the loop."""
        session = self._session_factory()
        try:
            account_ids = [item[0] for item in session.query(AdvertisingAccount.id).all()]
        finally:
            session.close()

        results: dict[int, dict] = {}
        for start in range(0, len(account_ids), self.health_batch_size):
            batch = account_ids[start : start + self.health_batch_size]
            batch_results = await asyncio.gather(
                *(self.validate_account(account_id) for account_id in batch),
                return_exceptions=True,
            )
            for account_id, result in zip(batch, batch_results, strict=True):
                results[account_id] = (
                    {"connected": False, "reason": type(result).__name__}
                    if isinstance(result, Exception)
                    else result
                )
            await asyncio.sleep(0)
        return results

    async def get_account_state(self, account_id: int) -> dict:
        session = self._session_factory()
        try:
            account = self._require_account(session, account_id)
            state = account.orchestration_state or self._derive_state(account).value
            return {
                "account_id": account.id,
                "state": state,
                "health_score": account.health_score or 0,
                "last_health_check": account.last_health_check,
                "error": account.orchestration_error or account.last_auth_error,
                "proxy_id": account.proxy_id,
                "queue_size": self.login_queue_size,
            }
        finally:
            session.close()

    async def disconnect_account(self, account_id: int, *, delete_file: bool) -> bool:
        async with self._account_operation(account_id):
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                await self._ensure_auth_mutation_allowed(
                    session,
                    account,
                    "disconnect_session",
                )
                await self.client_manager.disconnect_client(account_id)
                result = await disconnect_session(session, account, delete_file=delete_file)
                self._set_state(session, account, AccountState.REAUTH_REQUIRED)
                return result
            finally:
                session.close()

    async def run_client_operation(
        self,
        account_id: int,
        action: str,
        operation: Callable[[Any, AdvertisingAccount], Awaitable[Any] | Any],
    ) -> Any:
        """Run any Telethon operation through global/per-account safety gates."""
        if self._noncritical_frozen:
            raise OrchestratorError("Некритичные операции временно заморожены Autopilot")
        if account_id in self._disabled_accounts:
            raise OrchestratorError("Аккаунт отключён и исключён из отправки")
        async with self._account_operation(account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, account_id)
                if account.status == "disabled":
                    self._disabled_accounts.add(account_id)
                    raise OrchestratorError("Аккаунт отключён и исключён из отправки")
                self._assert_account_not_frozen(account)
                await self._ensure_proxy_ready(session, account)
                await self._throttle(account_id)
                client = await self.client_manager.get_client(account)
                value = operation(client, account)
                result = await value if inspect.isawaitable(value) else value
                self._log(account, action, "success", started)
                return result
            except FloodWaitError as error:
                self._record_event("flood_wait", account if "account" in locals() else None)
                self._safe_state_after_error(session, account_id, error)
                self._log_id(account_id, None, action, "flood_wait", started)
                raise
            except UnauthorizedError as error:
                self._record_event("unauthorized", account if "account" in locals() else None)
                self._safe_state_after_error(session, account_id, error)
                raise
            except (ConnectionError, TimeoutError, OSError) as error:
                event_type = "timeout" if isinstance(error, TimeoutError) else "connection_error"
                self._record_event(event_type, account if "account" in locals() else None)
                self._safe_state_after_error(session, account_id, error)
                raise
            finally:
                session.close()

    async def _login_worker(self, worker_id: int) -> None:
        while True:
            await self._login_resume_event.wait()
            job = await self._login_queue.get()
            try:
                if job is None:
                    return
                self._decrement_queued_login(job.account_id)
                try:
                    result = await self._execute_login_job(job)
                except Exception as error:
                    if not job.future.done():
                        job.future.set_exception(error)
                else:
                    if not job.future.done():
                        job.future.set_result(result)
            finally:
                self._login_queue.task_done()

    def _decrement_queued_login(self, account_id: int) -> None:
        self._queued_login_accounts[account_id] -= 1
        if self._queued_login_accounts[account_id] <= 0:
            self._queued_login_accounts.pop(account_id, None)

    async def _execute_login_job(self, job: _LoginJob) -> dict:
        async with self._account_operation(job.account_id):
            started = time.monotonic()
            session = self._session_factory()
            try:
                account = self._require_account(session, job.account_id)
                if (account.auth_generation or 0) != job.auth_generation:
                    raise OrchestratorError("Этот login flow устарел; начните авторизацию заново")
                account.login_attempt_count = (account.login_attempt_count or 0) + 1
                self._set_state(session, account, AccountState.AUTHENTICATING)
                if job.action == "request_code":
                    await self._drop_auth_context(job.account_id, "new_request_code")
                    await self.client_manager.disconnect_client(job.account_id)
                else:
                    context = self._get_auth_context(account, job.action)
                    self._debug_auth_context(context, job.action, context.client)
                await self._ensure_proxy_ready(session, account)
                await self._throttle(job.account_id)

                if job.action == "request_code":
                    result = await self._retry_login(
                        lambda: self._login_request_code(account)
                    )
                    if result.get("already_authorized"):
                        finalize_login_session(session, account)
                        await check_session_status(session, account)
                        account.login_attempt_count = 0
                        self._set_state(session, account, AccountState.ACTIVE)
                    self._log(account, "login_request_code", "success", started)
                    return result

                if job.action == "code":
                    if not job.code:
                        raise OrchestratorError("Не передан код")
                    context = self._get_auth_context(account, "code")
                    if (
                        job.phone_code_hash
                        and context.phone_code_hash
                        and job.phone_code_hash != context.phone_code_hash
                    ):
                        raise OrchestratorError(
                            "Код относится к другому login flow; запросите новый код"
                        )
                    try:
                        await self._retry_login(
                            lambda: self._login_confirm_code(account, context, job.code)
                        )
                    except SessionPasswordNeededError:
                        context.touch(AuthFlowState.PASSWORD_REQUIRED)
                        self._debug_auth_context(
                            context,
                            "password_required",
                            context.client,
                        )
                        self._set_state(session, account, AccountState.AUTHENTICATING)
                        return {"requires_password": True}
                else:
                    if not job.password:
                        raise OrchestratorError("Не передан пароль 2FA")
                    context = self._get_auth_context(account, "password")
                    await self._retry_login(
                        lambda: self._login_confirm_password(account, context, job.password)
                    )

                await self._finalize_auth_context(job.account_id, "authorized")
                finalize_login_session(session, account)
                status = await check_session_status(session, account)
                account.login_attempt_count = 0
                self._set_state(session, account, AccountState.ACTIVE)
                self._log(account, f"login_{job.action}", "success", started)
                return {"success": True, "status": status}
            except SessionPasswordNeededError:
                raise
            except Exception as error:
                event_type = self._event_type_for_error(error)
                if event_type:
                    self._record_event(
                        event_type,
                        account if "account" in locals() else None,
                        account_id=job.account_id,
                    )
                self._safe_state_after_error(session, job.account_id, error)
                self._log_id(job.account_id, None, f"login_{job.action}", "error", started)
                keep_password_context = (
                    job.action == "password"
                    and isinstance(error, TelethonAuthError)
                    and getattr(error, "keep_auth_context", False)
                )
                if (
                    job.action != "code"
                    and not isinstance(error, SessionPasswordNeededError)
                    and not keep_password_context
                ):
                    await self._drop_auth_context(job.account_id, f"login_error_{job.action}")
                raise
            finally:
                job.code = None
                job.phone_code_hash = None
                job.password = None
                session.close()

    async def _login_request_code(self, account: AdvertisingAccount) -> dict:
        if not account.phone_number:
            raise TelethonAuthError("Для аккаунта не указан номер телефона")

        client = create_account_client(account, for_login=True)
        context = AuthContext(
            account_id=account.id,
            client=client,
            phone=account.phone_number,
            auth_generation=account.auth_generation or 0,
            session_fingerprint=self._session_fingerprint(account),
        )
        self.auth_guard.register_context(account.id, context)
        self._debug_auth_context(context, "request_code_created", client)

        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            self._debug_auth_context(context, "request_code_connected", client)

            if await client.is_user_authorized():
                user = await client.get_me()
                context.touch(AuthFlowState.AUTHORIZED)
                logger.info(
                    "auth_context account_id=%s auth_context_id=%s step=already_authorized "
                    "session_fingerprint=%s is_same_client=%s user_id=%s",
                    account.id,
                    context.context_id,
                    context.session_fingerprint,
                    True,
                    getattr(user, "id", None),
                )
                await self._finalize_auth_context(account.id, "already_authorized")
                return {
                    "already_authorized": True,
                    "user_id": str(user.id),
                    "username": user.username,
                }

            try:
                result = await client.send_code_request(account.phone_number)
            except PhoneNumberInvalidError as error:
                raise TelethonAuthError("Telegram отклонил формат номера телефона") from error
            except FloodWaitError as error:
                raise TelethonAuthError(
                    f"Слишком много запросов. Повторите через {error.seconds} сек.",
                    retry_after=error.seconds,
                ) from error
            except RPCError as error:
                raise TelethonAuthError(
                    f"Telegram отклонил запрос ({type(error).__name__})"
                ) from error

            context.phone_code_hash = result.phone_code_hash
            context.touch(AuthFlowState.CODE_SENT)
            self._debug_auth_context(context, "code_sent", client)
            return {
                "already_authorized": False,
                "phone_code_hash": result.phone_code_hash,
                "delivery": self._describe_delivery(result),
                "timeout": getattr(result, "timeout", None),
            }
        except TelethonAuthError:
            await self._drop_auth_context(account.id, "request_code_error")
            raise
        except (asyncio.TimeoutError, ConnectionError, OSError) as error:
            await self._drop_auth_context(account.id, "request_code_connection_error")
            route = " через настроенный прокси" if account.proxy_enabled else ""
            raise TelethonAuthError(
                f"Не удалось подключиться к Telegram{route}. Проверьте сеть и прокси."
            ) from error
        except Exception as error:
            await self._drop_auth_context(account.id, "request_code_unexpected_error")
            raise TelethonAuthError(
                f"Не удалось запросить код ({type(error).__name__})"
            ) from error

    async def _login_confirm_code(
        self,
        account: AdvertisingAccount,
        context: AuthContext,
        phone_code: str,
    ) -> bool:
        if not phone_code or len(phone_code) < 4:
            raise TelethonAuthError("Неверный формат кода")
        if context.state != AuthFlowState.CODE_SENT:
            raise OrchestratorError("Код нельзя применить на текущем этапе авторизации")
        try:
            if not context.client.is_connected():
                await asyncio.wait_for(context.client.connect(), timeout=15)
            self._debug_auth_context(context, "code_sign_in", context.client)
            await context.client.sign_in(
                context.phone,
                phone_code,
                phone_code_hash=context.phone_code_hash,
            )
        except SessionPasswordNeededError:
            context.touch(AuthFlowState.PASSWORD_REQUIRED)
            raise
        except PhoneCodeInvalidError as error:
            raise TelethonAuthError("Telegram отклонил код. Проверьте цифры и повторите.") from error
        except PhoneCodeExpiredError as error:
            raise TelethonAuthError("Срок действия кода истёк. Запросите новый код.") from error
        except FloodWaitError as error:
            raise TelethonAuthError(
                f"Слишком много попыток. Повторите через {error.seconds} сек.",
                retry_after=error.seconds,
            ) from error
        except RPCError as error:
            raise TelethonAuthError(
                f"Telegram отклонил авторизацию ({type(error).__name__})"
            ) from error

        context.touch(AuthFlowState.CODE_VERIFIED)
        self._debug_auth_context(context, "code_verified", context.client)
        return True

    async def _login_confirm_password(
        self,
        account: AdvertisingAccount,
        context: AuthContext,
        password: str,
    ) -> bool:
        if not password:
            raise TelethonAuthError("Пароль не может быть пустым")
        if context.state != AuthFlowState.PASSWORD_REQUIRED:
            raise OrchestratorError("Пароль 2FA сейчас не ожидается")
        try:
            if not context.client.is_connected():
                await asyncio.wait_for(context.client.connect(), timeout=15)
            self._debug_auth_context(context, "password_sign_in", context.client)
            await context.client.sign_in(password=password)
        except PasswordHashInvalidError as error:
            context.password_attempts += 1
            remaining = max(0, 3 - context.password_attempts)
            auth_error = TelethonAuthError(
                "Пароль 2FA неверный. "
                + (
                    f"Осталось попыток: {remaining}."
                    if remaining > 0
                    else "Лимит попыток исчерпан. Нужно запросить код заново."
                )
            )
            auth_error.keep_auth_context = remaining > 0
            if remaining <= 0:
                context.touch(AuthFlowState.ERROR)
            raise auth_error from error
        except FloodWaitError as error:
            raise TelethonAuthError(
                f"Слишком много попыток. Повторите через {error.seconds} сек.",
                retry_after=error.seconds,
            ) from error
        except RPCError as error:
            raise TelethonAuthError(
                f"Telegram отклонил пароль ({type(error).__name__})"
            ) from error
        except Exception as error:
            raise TelethonAuthError(
                f"Telegram отклонил пароль ({type(error).__name__})"
            ) from error

        context.touch(AuthFlowState.AUTHORIZED)
        context.password_attempts = 0
        self._debug_auth_context(context, "password_verified", context.client)
        return True

    def _get_auth_context(
        self,
        account: AdvertisingAccount,
        step: str,
    ) -> AuthContext:
        try:
            context = self.auth_guard.get_context(account.id, step)
        except AuthGuardError as error:
            raise self._auth_guard_to_orchestrator_error(error) from error
        if context.auth_generation != (account.auth_generation or 0):
            raise OrchestratorError("Этот login flow устарел; начните авторизацию заново")
        if context.phone != account.phone_number:
            raise OrchestratorError("Номер аккаунта изменился. Запросите код заново.")
        return context

    async def _finalize_auth_context(self, account_id: int, reason: str) -> None:
        context = self.auth_guard.pop_context(account_id)
        if context is None:
            return
        self._debug_auth_context(context, reason, context.client)
        await context.client.disconnect()

    async def _drop_auth_context(self, account_id: int, reason: str) -> None:
        context = self.auth_guard.pop_context(account_id)
        if context is None:
            return
        logger.info(
            "auth_context account_id=%s auth_context_id=%s step=%s "
            "session_fingerprint=%s is_same_client=%s",
            account_id,
            context.context_id,
            reason,
            context.session_fingerprint,
            True,
        )
        with suppress(Exception):
            await context.client.disconnect()

    async def _drop_all_auth_contexts(self, reason: str) -> None:
        for account_id in list(self._auth_contexts.keys()):
            await self._drop_auth_context(account_id, reason)

    @staticmethod
    def _describe_delivery(sent_code) -> str:
        delivery_type = type(sent_code.type).__name__
        delivery_labels = {
            "SentCodeTypeApp": "в официальное приложение Telegram",
            "SentCodeTypeSms": "по SMS",
            "SentCodeTypeCall": "звонком",
            "SentCodeTypeFlashCall": "флеш-звонком",
            "SentCodeTypeMissedCall": "пропущенным звонком",
            "SentCodeTypeEmailCode": "на электронную почту",
            "SentCodeTypeFragmentSms": "через Fragment",
        }
        return delivery_labels.get(delivery_type, "выбранным Telegram способом")

    @staticmethod
    def _session_fingerprint(account: AdvertisingAccount) -> str:
        raw = "|".join(
            str(value or "")
            for value in (
                account.id,
                account.session_file_path,
                account.telethon_session,
                account.auth_generation,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    @staticmethod
    def _debug_auth_context(
        context: AuthContext,
        step: str,
        client: Any,
    ) -> None:
        logger.debug(
            "auth_context account_id=%s auth_context_id=%s step=%s "
            "state=%s session_fingerprint=%s is_same_client=%s",
            context.account_id,
            context.context_id,
            step,
            context.state.value,
            context.session_fingerprint,
            client is context.client,
        )

    async def _retry_login(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        for attempt in range(self.login_max_retries):
            try:
                return await operation()
            except SessionPasswordNeededError:
                raise
            except TelethonAuthError as error:
                event_type = self._event_type_for_error(error)
                if event_type:
                    self._record_event(event_type)
                retry_after = getattr(error, "retry_after", None)
                transient = retry_after is not None or any(
                    marker in str(error).lower()
                    for marker in ("подключ", "timeout", "временно")
                )
                if not transient or attempt + 1 >= self.login_max_retries:
                    raise
                delay = retry_after if retry_after is not None else 2**attempt
                if delay > 60:
                    raise
                await asyncio.sleep(max(1, delay))

    async def _throttle(self, account_id: int) -> None:
        now = time.monotonic()
        account_wait = max(0.0, self._next_account_at.get(account_id, 0.0) - now)
        if account_wait:
            await asyncio.sleep(account_wait)
        async with self._global_rate_lock:
            now = time.monotonic()
            global_wait = max(0.0, self._next_global_at - now)
            if global_wait:
                await asyncio.sleep(global_wait)
            finished = time.monotonic()
            self._next_global_at = finished + self.global_delay_seconds
            self._next_account_at[account_id] = finished + self.account_delay_seconds

    async def _ensure_proxy_ready(self, session, account: AdvertisingAccount) -> None:
        """Prevent an unverified/failed configured proxy from reaching Telethon."""
        if not account.proxy_enabled:
            return
        if not account.proxy_type:
            raise OrchestratorError("Тип прокси не определён")
        if account.proxy_status == "working":
            return
        await self._throttle(account.id)
        result = await run_fast_proxy_check(session, account)
        self._sync_endpoint_from_account(session, account)
        if not result.success:
            self._record_event("proxy_failure", account)
            raise OrchestratorError(
                f"Прокси не прошёл проверку: {account.proxy_last_error or 'Telegram недоступен'}"
            )

    @staticmethod
    def _require_account(session, account_id: int) -> AdvertisingAccount:
        account = session.get(AdvertisingAccount, account_id)
        if not account:
            raise OrchestratorError("Аккаунт не найден")
        return account

    async def _ensure_auth_mutation_allowed(
        self,
        session,
        account: AdvertisingAccount,
        action: str,
    ) -> None:
        await self._expire_auth_context_if_needed(
            account.id,
            session=session,
            account=account,
        )
        try:
            self.auth_guard.ensure_mutation_allowed(account.id, action)
        except AuthGuardError as error:
            raise self._auth_guard_to_orchestrator_error(error) from error

    async def _expire_auth_context_if_needed(
        self,
        account_id: int,
        *,
        session=None,
        account: AdvertisingAccount | None = None,
    ) -> bool:
        context = self.auth_guard.pop_expired_context(account_id)
        if context is None:
            return False
        with suppress(Exception):
            await context.client.disconnect()
        if session is not None:
            try:
                account = account or session.get(AdvertisingAccount, account_id)
                if account is not None:
                    account.orchestration_state = AccountState.CREATED.value
                    account.orchestration_error = "AUTH FLOW EXPIRED"
                    account.orchestration_updated_at = datetime.now(UTC).replace(
                        tzinfo=None
                    )
                    account.auth_status = "unverified"
                    update_persisted_health(session, account)
                    session.commit()
            except Exception:
                session.rollback()
                raise
        else:
            local_session = self._session_factory()
            try:
                account = local_session.get(AdvertisingAccount, account_id)
                if account is not None:
                    account.orchestration_state = AccountState.CREATED.value
                    account.orchestration_error = "AUTH FLOW EXPIRED"
                    account.orchestration_updated_at = datetime.now(UTC).replace(
                        tzinfo=None
                    )
                    account.auth_status = "unverified"
                    update_persisted_health(local_session, account)
                    local_session.commit()
            finally:
                local_session.close()
        logger.info(
            "auth_guard account_id=%s action=expire_cleanup auth_state=%s blocked_reason=%s ttl_remaining_ms=%s",
            account_id,
            "EXPIRED",
            "ttl_expired",
            0,
        )
        return True

    @staticmethod
    def _auth_guard_to_orchestrator_error(error: AuthGuardError) -> OrchestratorError:
        text = str(error)
        if text == "AUTH FLOW IN PROGRESS":
            return OrchestratorError(
                "AUTH FLOW IN PROGRESS: авторизация уже выполняется. "
                "Завершите ввод кода/2FA или сбросьте авторизацию."
            )
        if text == "AUTH FLOW EXPIRED":
            return OrchestratorError(
                "Контекст авторизации истёк. Запросите код заново."
            )
        if text == "AUTH CONTEXT MISSING":
            return OrchestratorError(
                "Контекст авторизации не найден. Запросите код заново."
            )
        if text.startswith("INVALID AUTH STATE"):
            return OrchestratorError(
                "Неверный этап авторизации. Запросите код заново."
            )
        return OrchestratorError(text)

    @staticmethod
    def _set_state(
        session,
        account: AdvertisingAccount,
        state: AccountState,
        error: str | None = None,
    ) -> None:
        account.orchestration_state = state.value
        account.orchestration_error = error
        account.orchestration_updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.commit()

    def _safe_state_after_error(self, session, account_id: int, error: Exception) -> None:
        with suppress(Exception):
            session.rollback()
            account = session.get(AdvertisingAccount, account_id)
            if not account:
                return
            if isinstance(error, (UnauthorizedError, AccountSessionError)):
                state = AccountState.REAUTH_REQUIRED
            elif isinstance(error, FloodWaitError) or getattr(error, "retry_after", None):
                state = AccountState.DEGRADED
            elif isinstance(error, TelethonAuthError):
                state = (
                    AccountState.DEGRADED
                    if any(
                        marker in str(error).lower()
                        for marker in ("подключ", "timeout", "сеть", "прокси")
                    )
                    else AccountState.REAUTH_REQUIRED
                )
            else:
                state = AccountState.ERROR
            self._set_state(
                session,
                account,
                state,
                f"{type(error).__name__}: операция не выполнена",
            )

    async def restart_account_session(self, account_id: int) -> dict:
        """Reconnect one cached client and revalidate without deleting its session."""
        await self.client_manager.disconnect_client(account_id)
        return await self.validate_account(account_id)

    def freeze_account(
        self,
        account_id: int,
        until: datetime,
        reason: str,
    ) -> None:
        session = self._session_factory()
        try:
            account = self._require_account(session, account_id)
            account.autopilot_frozen_until = until
            account.autopilot_freeze_reason = reason
            account.orchestration_state = AccountState.DEGRADED.value
            account.orchestration_error = reason
            account.orchestration_updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        finally:
            session.close()

    def unfreeze_account(self, account_id: int) -> None:
        session = self._session_factory()
        try:
            account = self._require_account(session, account_id)
            account.autopilot_frozen_until = None
            account.autopilot_freeze_reason = None
            session.commit()
        finally:
            session.close()

    @staticmethod
    def _assert_account_not_frozen(account: AdvertisingAccount) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        if account.autopilot_frozen_until and account.autopilot_frozen_until > now:
            raise OrchestratorError(
                f"Аккаунт временно заморожен: {account.autopilot_freeze_reason or 'защитный cooldown'}"
            )

    def _record_event(
        self,
        event_type: str,
        account: AdvertisingAccount | None = None,
        *,
        account_id: int | None = None,
    ) -> None:
        self._events.append(
            OperationEvent(
                time.monotonic(),
                event_type,
                account.id if account is not None else account_id,
                account.proxy_id if account is not None else None,
            )
        )

    @staticmethod
    def _event_type_for_error(error: Exception) -> str | None:
        if isinstance(error, FloodWaitError) or getattr(error, "retry_after", None):
            return "flood_wait"
        if isinstance(error, TimeoutError):
            return "timeout"
        if isinstance(error, (ConnectionError, OSError)):
            return "connection_error"
        text = str(error).lower()
        if "timeout" in text or "не ответил вовремя" in text:
            return "timeout"
        if "подключ" in text or "connection" in text:
            return "connection_error"
        return None

    @staticmethod
    def _derive_state(account: AdvertisingAccount) -> AccountState:
        if account.auth_status in {"error", "banned"}:
            return AccountState.ERROR
        if not account.session_connected:
            return AccountState.REAUTH_REQUIRED
        if account.proxy_enabled and account.proxy_status != "working":
            return AccountState.DEGRADED
        return AccountState.ACTIVE

    @staticmethod
    def _config_from_endpoint(endpoint: ProxyEndpoint) -> ParsedProxy:
        return ParsedProxy(
            endpoint.proxy_type,
            endpoint.host,
            endpoint.port,
            endpoint.username,
            endpoint.password,
            (endpoint.proxy_type,),
        )

    @staticmethod
    def _update_endpoint(
        endpoint: ProxyEndpoint, detection: ProxyDetectionResult
    ) -> None:
        endpoint.status = "working" if detection.success else "failed"
        endpoint.last_checked_at = datetime.now(UTC).replace(tzinfo=None)
        success = next((item for item in detection.attempts if item.success), None)
        endpoint.latency_ms = success.latency_ms if success else None
        endpoint.last_error = None if success else (
            detection.attempts[-1].error if detection.attempts else "Проверка не выполнена"
        )
        detected_type = AccountOrchestrator._get_detected_proxy_type(
            detection,
            endpoint.proxy_type,
        )
        if detected_type:
            endpoint.proxy_type = detected_type
        if detection.success:
            endpoint.enabled = True
            endpoint.disabled_until = None
            endpoint.success_count = (endpoint.success_count or 0) + 1
        else:
            endpoint.failure_count = (endpoint.failure_count or 0) + 1
        AccountOrchestrator._recalculate_proxy_score(endpoint)

    def _find_or_create_endpoint(
        self,
        session,
        config: ParsedProxy,
        detection: ProxyDetectionResult | None,
    ) -> ProxyEndpoint:
        proxy_type = self._get_detected_proxy_type(detection, config.proxy_type)
        endpoint = (
            session.query(ProxyEndpoint)
            .filter(
                ProxyEndpoint.proxy_type == proxy_type,
                ProxyEndpoint.host == config.host,
                ProxyEndpoint.port == config.port,
                ProxyEndpoint.username == config.username,
                ProxyEndpoint.password == config.password,
            )
            .first()
        )
        if endpoint is None:
            endpoint = ProxyEndpoint(
                proxy_type=proxy_type or "SOCKS5",
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
            )
            session.add(endpoint)
            session.flush()
        if detection:
            self._update_endpoint(endpoint, detection)
        return endpoint

    @staticmethod
    def _get_detected_proxy_type(
        detection: ProxyDetectionResult | None,
        fallback: str | None,
    ) -> str | None:
        """Resolve the successful proxy type across compatible result shapes."""
        if not detection or not detection.success:
            return fallback
        detected_type = getattr(detection, "detected_type", None)
        if detected_type:
            return detected_type
        working_type = getattr(detection, "working_type", None)
        if working_type:
            return working_type
        success_attempt = next(
            (attempt for attempt in getattr(detection, "attempts", ()) if attempt.success),
            None,
        )
        return success_attempt.proxy_type if success_attempt else fallback

    @staticmethod
    def _sync_endpoint_from_account(session, account: AdvertisingAccount) -> None:
        if not account.proxy_id:
            return
        endpoint = session.get(ProxyEndpoint, account.proxy_id)
        if not endpoint:
            return
        endpoint.status = account.proxy_status
        endpoint.latency_ms = account.proxy_latency_ms
        endpoint.last_checked_at = account.proxy_last_checked_at
        endpoint.last_error = account.proxy_last_error
        if account.proxy_status == "working":
            endpoint.success_count = (endpoint.success_count or 0) + 1
        elif account.proxy_status == "failed":
            endpoint.failure_count = (endpoint.failure_count or 0) + 1
        AccountOrchestrator._recalculate_proxy_score(endpoint)
        session.commit()

    @staticmethod
    def _recalculate_proxy_score(endpoint: ProxyEndpoint) -> None:
        successes = endpoint.success_count or 0
        failures = endpoint.failure_count or 0
        total = successes + failures
        reliability = 100 if total == 0 else round(100 * successes / total)
        latency_penalty = 0
        if endpoint.latency_ms is not None:
            if endpoint.latency_ms > 3000:
                latency_penalty = 30
            elif endpoint.latency_ms > 1500:
                latency_penalty = 15
            elif endpoint.latency_ms > 750:
                latency_penalty = 5
        endpoint.score = max(0, min(100, reliability - latency_penalty))

    def _log(
        self,
        account: AdvertisingAccount,
        action: str,
        status: str,
        started: float,
    ) -> None:
        self._log_id(account.id, account.proxy_id, action, status, started)

    @staticmethod
    def _log_id(
        account_id: int,
        proxy_id: int | None,
        action: str,
        status: str,
        started: float,
    ) -> None:
        logger.info(
            "account_operation account_id=%s proxy_id=%s action=%s status=%s latency_ms=%s",
            account_id,
            proxy_id,
            action,
            status,
            round((time.monotonic() - started) * 1000),
        )


account_orchestrator = AccountOrchestrator()
