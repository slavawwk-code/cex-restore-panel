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
    """Calculate a read-only 100-point operational health score."""
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
    proxy_last_ok = bool(account.proxy_last_check_success is True)
    account_enabled = account.status != "disabled"
    templates_ok = bool(template_ids)
    chats_ok = bool(active_chats)
    errors_ok = recent_errors == 0

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
            "Последняя проверка прокси",
            10 if proxy_last_ok else 0,
            10,
            proxy_last_ok,
            None if proxy_last_ok else account.proxy_last_error or "Нет успешной проверки",
        ),
        HealthComponent(
            "Планировщик",
            15 if scheduler_running else 0,
            15,
            scheduler_running,
            None if scheduler_running else "Планировщик остановлен",
        ),
        HealthComponent(
            "Аккаунт",
            15 if account_enabled else 0,
            15,
            account_enabled,
            None if account_enabled else "Аккаунт отключён",
        ),
        HealthComponent(
            "Шаблоны",
            10 if templates_ok else 0,
            10,
            templates_ok,
            None if templates_ok else "Не назначены активным чатам",
        ),
        HealthComponent(
            "Чаты",
            10 if chats_ok else 0,
            10,
            chats_ok,
            None if chats_ok else "Нет активных чатов",
        ),
        HealthComponent(
            "Ошибки отправки",
            10 if errors_ok else 0,
            10,
            errors_ok,
            None if errors_ok else f"Ошибок за 24 часа: {recent_errors}",
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
        if value is not None
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
