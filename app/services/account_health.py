from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import AdvertisingAccount, Chat, SendLog


@dataclass(frozen=True)
class HealthComponent:
    label: str
    points: int
    maximum: int
    healthy: bool
    reason: str | None = None


@dataclass(frozen=True)
class AccountHealth:
    account_id: int
    score: int
    components: tuple[HealthComponent, ...]
    chat_count: int
    active_chat_count: int
    template_count: int
    recent_error_count: int
    last_activity_at: datetime | None


def calculate_account_health(
    session: Session,
    account: AdvertisingAccount,
    scheduler_running: bool,
) -> AccountHealth:
    """Calculate a read-only 100-point Telegram account health score."""
    chats = (
        session.query(Chat)
        .filter(Chat.advertising_account_id == account.id, Chat.is_active.is_(True))
        .all()
    )
    active_chats = [chat for chat in chats if chat.status == "active"]
    template_ids = {
        chat.assigned_template_id
        for chat in chats
        if chat.assigned_template_id is not None
        and chat.template is not None
        and chat.template.is_active
    }
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    recent_errors = (
        session.query(SendLog)
        .filter(
            SendLog.account_id == account.id,
            SendLog.status == "error",
            SendLog.sent_at >= since,
        )
        .count()
    )
    last_send_at = (
        session.query(func.max(SendLog.sent_at))
        .filter(SendLog.account_id == account.id)
        .scalar()
    )

    telegram_ok = bool(account.session_connected)
    proxy_working = bool(account.proxy_enabled and account.proxy_status == "working")
    session_configured = bool(
        account.session_file_path
        or account.string_session
        or account.telethon_session
    )
    session_valid = bool(account.session_connected and session_configured)
    no_auth_errors = bool(
        not account.last_auth_error
        and account.auth_status not in {"banned", "error"}
    )
    fully_active = bool(
        account.status == "active"
        and (
            account.auth_status == "active"
            or (account.auth_status in {None, "unverified"} and telegram_ok)
        )
    )

    components = (
        HealthComponent(
            "Telegram",
            20 if telegram_ok else 0,
            20,
            telegram_ok,
            None if telegram_ok else "Сессия не авторизована",
        ),
        HealthComponent(
            "Прокси",
            10 if proxy_working else 0,
            10,
            proxy_working,
            None
            if proxy_working
            else account.proxy_last_error
            or ("Прокси отключён" if not account.proxy_enabled else "Нет успешной проверки"),
        ),
        HealthComponent(
            "Сессия",
            20 if session_valid else 0,
            20,
            session_valid,
            None if session_valid else "Нет валидной file/string session",
        ),
        HealthComponent(
            "Ошибки авторизации",
            20 if no_auth_errors else 0,
            20,
            no_auth_errors,
            None if no_auth_errors else account.last_auth_error or "Ошибка авторизации",
        ),
        HealthComponent(
            "Аккаунт",
            30 if fully_active else 0,
            30,
            fully_active,
            None if fully_active else "Аккаунт не полностью активен",
        ),
    )
    timestamps = [
        value
        for value in (
            last_send_at,
            account.proxy_last_checked_at,
            account.session_last_checked_at,
            account.created_at,
        )
        if isinstance(value, datetime)
    ]
    return AccountHealth(
        account_id=account.id,
        score=sum(component.points for component in components),
        components=components,
        chat_count=len(chats),
        active_chat_count=len(active_chats),
        template_count=len(template_ids),
        recent_error_count=recent_errors,
        last_activity_at=max(timestamps) if timestamps else None,
    )


def update_persisted_health(
    session: Session,
    account: AdvertisingAccount,
    commit: bool = False,
) -> AccountHealth:
    """Refresh cached health fields after auth/proxy/account state changes."""
    health = calculate_account_health(session, account, scheduler_running=True)
    account.health_score = health.score
    account.last_health_check = datetime.now(UTC).replace(tzinfo=None)
    if commit:
        session.commit()
    else:
        session.flush()
    return health


def health_indicator(score: int) -> str:
    if score >= 90:
        return "🟢"
    if score >= 60:
        return "🟡"
    return "🔴"


def system_health_score(accounts: list[AccountHealth]) -> int:
    if not accounts:
        return 0
    return round(sum(account.score for account in accounts) / len(accounts))
