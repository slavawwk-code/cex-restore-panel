import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import load_settings
from app.database import get_session
from app.database.models import AdvertisingAccount
from app.services.account_orchestrator import (
    AccountOrchestrator,
    AccountState,
    OrchestratorError,
    account_orchestrator,
)
from app.services.autopilot_engine import AutopilotEngine, autopilot_engine

logger = logging.getLogger(__name__)


class AccountLifecycleError(RuntimeError):
    """Safe lifecycle error suitable for the operator interface."""


@dataclass(frozen=True)
class LifecycleResult:
    account_id: int
    action: str
    result: str
    reason: str | None = None
    next_action: str | None = None


class AccountLifecycleManager:
    """Safe hard-delete, soft-disable, and reauthentication coordination."""

    def __init__(
        self,
        orchestrator: AccountOrchestrator = account_orchestrator,
        *,
        session_factory=get_session,
        sessions_dir: Path | None = None,
        autopilot: AutopilotEngine = autopilot_engine,
    ) -> None:
        self.orchestrator = orchestrator
        self._session_factory = session_factory
        self._sessions_dir = (
            sessions_dir or load_settings(require_secrets=False).sessions_dir
        ).resolve()
        self._autopilot = autopilot
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def delete_account(
        self,
        account_id: int,
        *,
        force: bool = False,
    ) -> LifecycleResult:
        """Hard-delete after runtime drain; active work requires force=True."""
        lock = self._locks[account_id]
        async with lock:
            result = await self._delete_account(account_id, force=force)
        self._locks.pop(account_id, None)
        return result

    async def _delete_account(
        self,
        account_id: int,
        *,
        force: bool,
    ) -> LifecycleResult:
        self._load_account(account_id)
        try:
            await self.orchestrator.prepare_account_removal(
                account_id,
                force=force,
            )
        except OrchestratorError as error:
            self._log(account_id, "delete", "blocked", str(error))
            raise AccountLifecycleError(str(error)) from error
        except TimeoutError as error:
            self._log(account_id, "delete", "timeout", "graceful shutdown timeout")
            raise AccountLifecycleError(
                "Не удалось дождаться завершения операций аккаунта"
            ) from error
        except Exception as error:
            self._log(account_id, "delete", "error", type(error).__name__)
            raise AccountLifecycleError("Не удалось остановить операции аккаунта") from error

        account = self._load_account(account_id)
        session_paths = self._exclusive_session_paths(account)
        quarantined: list[tuple[Path, Path]] = []
        try:
            quarantined = self._archive_session_files(
                session_paths,
                account_id,
                directory_name="delete_pending",
            )
        except OSError as error:
            self.orchestrator.abort_account_removal(account_id)
            self._log(account_id, "delete", "error", type(error).__name__)
            raise AccountLifecycleError("Не удалось подготовить session-файл к удалению") from error

        session = self._session_factory()
        try:
            persisted = session.get(AdvertisingAccount, account_id)
            if persisted is None:
                raise AccountLifecycleError("Аккаунт не найден")
            persisted.proxy_id = None
            session.delete(persisted)
            session.commit()
        except Exception as error:
            session.rollback()
            self._restore_archived_files(quarantined)
            self.orchestrator.abort_account_removal(account_id)
            self._log(account_id, "delete", "error", type(error).__name__)
            if isinstance(error, AccountLifecycleError):
                raise
            raise AccountLifecycleError("Не удалось удалить аккаунт из базы") from error
        finally:
            session.close()

        file_errors = self._delete_session_files(
            {archived_path for _, archived_path in quarantined}
        )
        self.orchestrator.forget_account(account_id)
        self._autopilot.forget_account(account_id)
        reason = "; ".join(file_errors) if file_errors else None
        result = "partial" if file_errors else "success"
        self._log(account_id, "delete", result, reason or "complete")
        return LifecycleResult(account_id, "delete", result, reason)

    async def disable_account(
        self,
        account_id: int,
        *,
        reason: str = "Отключено оператором",
    ) -> LifecycleResult:
        """Soft-disable scheduling/runtime while preserving credentials and DB."""
        async with self._locks[account_id]:
            return await self._disable_account(account_id, reason=reason)

    async def _disable_account(
        self,
        account_id: int,
        *,
        reason: str,
    ) -> LifecycleResult:
        self._load_account(account_id)
        try:
            await self.orchestrator.disable_runtime_account(account_id)
        except Exception as error:
            self._log(account_id, "disable", "error", type(error).__name__)
            raise AccountLifecycleError("Не удалось остановить аккаунт") from error
        session = self._session_factory()
        try:
            account = session.get(AdvertisingAccount, account_id)
            if account is None:
                raise AccountLifecycleError("Аккаунт не найден")
            now = self._utc_now()
            account.status = "disabled"
            account.disabled_at = now
            account.lifecycle_updated_at = now
            account.lifecycle_reason = reason
            account.orchestration_state = AccountState.DEGRADED.value
            account.orchestration_error = reason
            account.orchestration_updated_at = now
            session.commit()
        except Exception as error:
            session.rollback()
            self.orchestrator.activate_account_for_reauth(account_id)
            self._log(account_id, "disable", "error", type(error).__name__)
            if isinstance(error, AccountLifecycleError):
                raise
            raise AccountLifecycleError("Не удалось отключить аккаунт") from error
        finally:
            session.close()
        self._log(account_id, "disable", "success", reason)
        return LifecycleResult(account_id, "disable", "success", reason)

    async def reauth_account(
        self,
        account_id: int,
        *,
        reason: str = "Повторная авторизация запрошена оператором",
    ) -> LifecycleResult:
        """Invalidate bindings, preserve session file in archive, and restart login."""
        async with self._locks[account_id]:
            return await self._reauth_account(account_id, reason=reason)

    async def _reauth_account(
        self,
        account_id: int,
        *,
        reason: str,
    ) -> LifecycleResult:
        self._load_account(account_id)
        try:
            await self.orchestrator.prepare_account_reauth(account_id)
        except Exception as error:
            self._log(account_id, "reauth", "error", type(error).__name__)
            raise AccountLifecycleError("Не удалось остановить текущую сессию") from error
        account = self._load_account(account_id)
        archived: list[tuple[Path, Path]] = []
        try:
            archived = self._archive_session_files(
                self._exclusive_session_paths(account), account_id
            )
            session = self._session_factory()
            try:
                persisted = session.get(AdvertisingAccount, account_id)
                if persisted is None:
                    raise AccountLifecycleError("Аккаунт не найден")
                now = self._utc_now()
                generation = (persisted.auth_generation or 0) + 1
                persisted.status = "warming"
                persisted.auth_status = "unverified"
                persisted.orchestration_state = AccountState.REAUTH_REQUIRED.value
                persisted.orchestration_error = reason
                persisted.orchestration_updated_at = now
                persisted.reauth_requested_at = now
                persisted.lifecycle_updated_at = now
                persisted.lifecycle_reason = reason
                persisted.disabled_at = None
                persisted.session_connected = False
                persisted.session_connected_at = None
                persisted.session_last_checked_at = None
                persisted.session_user_id = None
                persisted.session_username = None
                persisted.session_file_path = None
                persisted.string_session = None
                persisted.last_auth_error = None
                persisted.last_error = None
                persisted.health_score = 0
                persisted.last_health_check = None
                persisted.login_attempt_count = 0
                persisted.auth_generation = generation
                persisted.telethon_session = f"account_{account_id}_generation_{generation}"
                persisted.proxy_id = None
                persisted.proxy_enabled = False
                persisted.proxy_type = None
                persisted.proxy_host = None
                persisted.proxy_port = None
                persisted.proxy_username = None
                persisted.proxy_password = None
                persisted.proxy_status = "unknown"
                persisted.proxy_last_check_at = None
                persisted.proxy_last_check_success = None
                persisted.proxy_last_checked_at = None
                persisted.proxy_last_success_at = None
                persisted.proxy_last_error = None
                persisted.proxy_latency_ms = None
                persisted.proxy_detected_type = None
                persisted.proxy_diagnostics = None
                persisted.autopilot_frozen_until = None
                persisted.autopilot_freeze_reason = None
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as error:
            self._restore_archived_files(archived)
            self.orchestrator.activate_account_for_reauth(account_id)
            self._log(account_id, "reauth", "error", type(error).__name__)
            if isinstance(error, AccountLifecycleError):
                raise
            raise AccountLifecycleError("Не удалось сбросить авторизацию") from error

        self.orchestrator.activate_account_for_reauth(account_id)
        self._autopilot.forget_account(account_id)
        self._log(account_id, "reauth", "success", reason)
        return LifecycleResult(
            account_id,
            "reauth",
            "success",
            reason,
            next_action=f"auth_methods_{account_id}",
        )

    def _load_account(self, account_id: int) -> AdvertisingAccount:
        session = self._session_factory()
        try:
            account = session.get(AdvertisingAccount, account_id)
            if account is None:
                raise AccountLifecycleError("Аккаунт не найден")
            session.expunge(account)
            return account
        finally:
            session.close()

    def _exclusive_session_paths(self, account: AdvertisingAccount) -> set[Path]:
        candidates = {
            self._safe_session_path(account.session_file_path),
            self._safe_session_path(account.telethon_session),
            self._safe_session_path(f"{account.id}.session"),
        }
        candidates.discard(None)
        session = self._session_factory()
        try:
            others = (
                session.query(AdvertisingAccount)
                .filter(AdvertisingAccount.id != account.id)
                .all()
            )
            shared = {
                path
                for other in others
                for path in (
                    self._safe_session_path(other.session_file_path),
                    self._safe_session_path(other.telethon_session),
                )
                if path is not None
            }
        finally:
            session.close()
        return {path for path in candidates if path not in shared and path.is_file()}

    def _safe_session_path(self, value: str | None) -> Path | None:
        if not value:
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self._sessions_dir / candidate
        if candidate.suffix != ".session":
            candidate = candidate.with_suffix(".session")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self._sessions_dir)
        except ValueError:
            logger.warning("Rejected lifecycle session path outside sessions directory")
            return None
        return resolved

    def _archive_session_files(
        self,
        paths: set[Path],
        account_id: int,
        *,
        directory_name: str = "reauth_archive",
    ) -> list[tuple[Path, Path]]:
        if not paths:
            return []
        archive_dir = self._sessions_dir / directory_name
        archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        archived: list[tuple[Path, Path]] = []
        for index, source in enumerate(sorted(paths)):
            destination = archive_dir / f"account_{account_id}_{timestamp}_{index}.session"
            os.replace(source, destination)
            destination.chmod(0o600)
            archived.append((source, destination))
        return archived

    @staticmethod
    def _restore_archived_files(archived: list[tuple[Path, Path]]) -> None:
        for source, archived_path in reversed(archived):
            if archived_path.exists():
                os.replace(archived_path, source)
                source.chmod(0o600)

    @staticmethod
    def _delete_session_files(paths: set[Path]) -> list[str]:
        errors: list[str] = []
        for path in paths:
            for candidate in (
                path,
                Path(f"{path}-journal"),
                Path(f"{path}-wal"),
                Path(f"{path}-shm"),
            ):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError as error:
                    errors.append(f"{candidate.name}: {type(error).__name__}")
        return errors

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _log(account_id: int, action: str, result: str, reason: str) -> None:
        logger.info(
            "account_lifecycle account_id=%s action=%s result=%s reason=%s",
            account_id,
            action,
            result,
            reason,
        )


account_lifecycle_manager = AccountLifecycleManager()
