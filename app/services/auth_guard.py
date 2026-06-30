import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

AUTH_FLOW_IN_PROGRESS = "AUTH FLOW IN PROGRESS"
DEFAULT_AUTH_CONTEXT_TTL_SECONDS = 10 * 60


class AuthGuardState(StrEnum):
    CREATED = "CREATED"
    CODE_SENT = "CODE_SENT"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


class AuthGuardError(RuntimeError):
    """Safe auth guard failure that can be shown to an operator."""


@dataclass(frozen=True)
class AuthGuardDecision:
    allowed: bool
    reason: str | None = None
    ttl_remaining_ms: int | None = None


class AuthGuard:
    """Single source of truth for in-memory auth-flow safety gates."""

    def __init__(self, *, ttl_seconds: int = DEFAULT_AUTH_CONTEXT_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self.contexts: dict[int, Any] = {}
        self._pending_accounts: dict[int, str] = {}

    def ttl_remaining_ms(self, account_id: int) -> int | None:
        context = self.contexts.get(account_id)
        if context is None:
            return None
        return self._ttl_remaining_ms(context)

    def has_live_context(self, account_id: int) -> bool:
        context = self.contexts.get(account_id)
        return context is not None and not self._is_expired(context)

    def has_pending_auth(self, account_id: int) -> bool:
        return account_id in self._pending_accounts

    def begin_auth_operation(
        self,
        account_id: int,
        action: str,
        *,
        force_reset: bool = False,
    ) -> None:
        context = self.contexts.get(account_id)
        if context is not None and self._is_expired(context):
            raise AuthGuardError("AUTH FLOW EXPIRED")

        pending_action = self._pending_accounts.get(account_id)
        if pending_action:
            self._log_block(
                account_id,
                action,
                self._state_name(context),
                AUTH_FLOW_IN_PROGRESS,
                self._ttl_remaining_ms(context) if context is not None else None,
            )
            raise AuthGuardError(AUTH_FLOW_IN_PROGRESS)

        if action == "request_code":
            if context is not None:
                state = self._state_name(context)
                if state in {
                    AuthGuardState.CODE_SENT.value,
                    AuthGuardState.PASSWORD_REQUIRED.value,
                } and not force_reset:
                    self._log_block(
                        account_id,
                        action,
                        state,
                        AUTH_FLOW_IN_PROGRESS,
                        self._ttl_remaining_ms(context),
                    )
                    raise AuthGuardError(AUTH_FLOW_IN_PROGRESS)
        elif action == "code":
            self._require_context_state(
                account_id,
                context,
                action,
                {AuthGuardState.CODE_SENT.value},
            )
        elif action == "password":
            self._require_context_state(
                account_id,
                context,
                action,
                {AuthGuardState.PASSWORD_REQUIRED.value},
            )
        else:
            raise AuthGuardError("UNKNOWN AUTH ACTION")

        self._pending_accounts[account_id] = action
        logger.info(
            "auth_guard account_id=%s action=%s auth_state=%s blocked_reason=%s ttl_remaining_ms=%s",
            account_id,
            action,
            self._state_name(context),
            None,
            self._ttl_remaining_ms(context) if context is not None else None,
        )

    def finish_auth_operation(self, account_id: int) -> None:
        self._pending_accounts.pop(account_id, None)

    def register_context(self, account_id: int, context: Any) -> None:
        created_at = getattr(context, "created_at", time.monotonic())
        context.created_at = created_at
        context.expires_at = created_at + self.ttl_seconds
        self.contexts[account_id] = context
        logger.info(
            "auth_guard account_id=%s action=register_context auth_state=%s blocked_reason=%s ttl_remaining_ms=%s",
            account_id,
            self._state_name(context),
            None,
            self._ttl_remaining_ms(context),
        )

    def get_context(self, account_id: int, action: str) -> Any:
        context = self.contexts.get(account_id)
        if context is not None and self._is_expired(context):
            raise AuthGuardError("AUTH FLOW EXPIRED")
        if action == "code":
            self._require_context_state(
                account_id,
                context,
                action,
                {AuthGuardState.CODE_SENT.value},
            )
        elif action == "password":
            self._require_context_state(
                account_id,
                context,
                action,
                {AuthGuardState.PASSWORD_REQUIRED.value},
            )
        else:
            if context is None:
                raise AuthGuardError("AUTH CONTEXT MISSING")
        return context

    def pop_context(self, account_id: int) -> Any | None:
        self.finish_auth_operation(account_id)
        return self.contexts.pop(account_id, None)

    def pop_expired_context(self, account_id: int) -> Any | None:
        context = self.contexts.get(account_id)
        if context is None or not self._is_expired(context):
            return None
        self._set_state(context, AuthGuardState.EXPIRED.value)
        self.finish_auth_operation(account_id)
        self.contexts.pop(account_id, None)
        logger.info(
            "auth_guard account_id=%s action=expire_context auth_state=%s blocked_reason=%s ttl_remaining_ms=%s",
            account_id,
            AuthGuardState.EXPIRED.value,
            "ttl_expired",
            0,
        )
        return context

    def ensure_mutation_allowed(self, account_id: int, action: str) -> None:
        context = self.contexts.get(account_id)
        if context is not None and self._is_expired(context):
            raise AuthGuardError("AUTH FLOW EXPIRED")
        if context is not None or self.has_pending_auth(account_id):
            state = self._state_name(context)
            ttl = self._ttl_remaining_ms(context) if context is not None else None
            self._log_block(account_id, action, state, AUTH_FLOW_IN_PROGRESS, ttl)
            raise AuthGuardError(AUTH_FLOW_IN_PROGRESS)

    def reset_account(self, account_id: int) -> Any | None:
        self.finish_auth_operation(account_id)
        return self.contexts.pop(account_id, None)

    def _require_context_state(
        self,
        account_id: int,
        context: Any | None,
        action: str,
        allowed_states: set[str],
    ) -> None:
        if context is None:
            self._log_block(account_id, action, None, "AUTH CONTEXT MISSING", None)
            raise AuthGuardError("AUTH CONTEXT MISSING")
        state = self._state_name(context)
        if state not in allowed_states:
            self._log_block(
                account_id,
                action,
                state,
                f"INVALID AUTH STATE: {state}",
                self._ttl_remaining_ms(context),
            )
            raise AuthGuardError(f"INVALID AUTH STATE: {state}")

    def _is_expired(self, context: Any) -> bool:
        expires_at = getattr(context, "expires_at", None)
        if expires_at is None:
            expires_at = getattr(context, "created_at", time.monotonic()) + self.ttl_seconds
            context.expires_at = expires_at
        return time.monotonic() >= expires_at

    @staticmethod
    def _state_name(context: Any | None) -> str | None:
        if context is None:
            return None
        state = getattr(context, "state", None)
        return getattr(state, "value", state)

    @staticmethod
    def _set_state(context: Any, state: str) -> None:
        current = getattr(context, "state", None)
        enum_type = type(current) if current is not None else None
        try:
            context.state = enum_type(state) if enum_type else state
        except Exception:
            context.state = state

    @staticmethod
    def _ttl_remaining_ms(context: Any) -> int:
        expires_at = getattr(context, "expires_at", None)
        if expires_at is None:
            return 0
        return max(0, round((expires_at - time.monotonic()) * 1000))

    @staticmethod
    def _log_block(
        account_id: int,
        action: str,
        auth_state: str | None,
        blocked_reason: str,
        ttl_remaining_ms: int | None,
    ) -> None:
        logger.warning(
            "auth_guard account_id=%s action=%s auth_state=%s blocked_reason=%s ttl_remaining_ms=%s",
            account_id,
            action,
            auth_state,
            blocked_reason,
            ttl_remaining_ms,
        )
