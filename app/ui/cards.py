import os
from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database.models import AdvertisingAccount, ProxyCheckHistory
from app.services.account_health import AccountHealth, health_indicator

SEPARATOR = "────────────────────"


def format_datetime(value: datetime | None, time_only: bool = False) -> str:
    if value is None:
        return "—"
    try:
        timezone = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))
    except ZoneInfoNotFoundError:
        timezone = UTC
    aware_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    pattern = "%H:%M" if time_only else "%d.%m.%Y %H:%M"
    return aware_value.astimezone(timezone).strftime(pattern)


def mask_phone(phone: str) -> str:
    if len(phone) <= 6:
        return "•" * len(phone)
    prefix_length = 2 if phone.startswith("+") else 1
    return phone[:prefix_length] + "•" * 6 + phone[-4:]


def mask_proxy_host(host: str | None) -> str:
    if not host:
        return "—"
    parts = host.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return f"{parts[0]}.xxx.xxx.xxx"
    if len(host) <= 4:
        return "••••"
    return f"{host[:3]}•••{host[-3:]}"


def account_status(account: AdvertisingAccount) -> str:
    return {
        "active": "🟢 Активен",
        "paused": "⚪ На паузе",
        "warming": "🟡 Прогрев",
        "disabled": "⚪ Отключён",
        "banned": "🔴 Заблокирован",
        "error": "🔴 Ошибка",
        "unverified": "🟡 Не проверен",
    }.get(account.status, "🟡 Требует проверки")


def orchestration_status(account: AdvertisingAccount) -> str:
    return {
        "CREATED": "⚪ Создан",
        "AUTHENTICATING": "🟡 Авторизация",
        "ACTIVE": "🟢 Активен",
        "DEGRADED": "🟡 Ограниченная работа",
        "ERROR": "🔴 Ошибка",
        "REAUTH_REQUIRED": "🔴 Нужна повторная авторизация",
    }.get(account.orchestration_state or "CREATED", "🟡 Требует проверки")


def format_account_card(
    account: AdvertisingAccount,
    health: AccountHealth,
) -> str:
    telegram = "🟢 Авторизован" if account.session_connected else "🔴 Не авторизован"
    if not account.proxy_enabled:
        proxy = "⚪ Отключён"
    elif account.proxy_status == "working":
        proxy = f"🟢 {escape(account.proxy_type or 'Работает')}"
    elif account.proxy_status == "failed":
        proxy = "🔴 Недоступен"
    else:
        proxy = "🟡 Не проверен"
    auth_status = {
        "active": "🟢 Active",
        "banned": "🔴 Banned",
        "error": "🔴 Error",
        "unverified": "🟡 Unverified",
    }.get(account.auth_status or "unverified", "🟡 Unverified")
    auth_error = (
        account.orchestration_error or account.last_auth_error or account.last_error
    )
    return (
        f"<b>{escape(account.display_name)}</b>\n\n"
        f"{SEPARATOR}\n\n"
        f"Телефон\n{escape(mask_phone(account.phone_number))}\n\n"
        f"Статус\n{account_status(account)}\n\n"
        f"Состояние управления\n{orchestration_status(account)}\n\n"
        f"Telegram\n{telegram}\n\n"
        f"Авторизация\n{auth_status}\n\n"
        f"Прокси\n{proxy}\n\n"
        f"Профиль устройства\n"
        f"{escape(account.device_model or '—')} · {escape(account.system_version or '—')}\n"
        f"Telegram Desktop {escape(account.app_version or '—')}\n\n"
        f"Чаты\n{health.chat_count}\n\n"
        f"Шаблоны\n{health.template_count}\n\n"
        f"Последняя активность\n{format_datetime(health.last_activity_at)}\n\n"
        f"Последняя проверка\n{format_datetime(account.last_health_check)}\n\n"
        f"Ошибка\n{escape(auth_error or '—')}\n\n"
        f"Health\n{health_indicator(health.score)} {health.score}%\n\n"
        f"{SEPARATOR}"
    )


def format_account_identity_card(account: AdvertisingAccount) -> str:
    return (
        f"<b>Профиль устройства · {escape(account.display_name)}</b>\n\n"
        f"{SEPARATOR}\n\n"
        f"Устройство\n{escape(account.device_model or '—')}\n\n"
        f"OS\n{escape(account.system_version or '—')}\n\n"
        f"Версия Telegram Desktop\n{escape(account.app_version or '—')}\n\n"
        f"Язык\n{escape(account.lang_code or '—')} / {escape(account.system_lang_code or '—')}\n\n"
        f"Часовой пояс\n{escape(account.timezone or '—')}\n\n"
        f"Создан\n{format_datetime(account.identity_created_at)}\n\n"
        f"{SEPARATOR}"
    )


def format_accounts_list(
    accounts: list[tuple[AdvertisingAccount, AccountHealth]],
) -> str:
    lines = ["<b>Аккаунты</b>", "", SEPARATOR, ""]
    for account, health in accounts:
        lines.extend(
            [
                escape(account.display_name),
                f"{health_indicator(health.score)} {health.score}% · {health.active_chat_count} активных чатов",
                "",
            ]
        )
    lines.append(SEPARATOR)
    return "\n".join(lines)


def format_account_health_card(
    account: AdvertisingAccount,
    health: AccountHealth,
) -> str:
    lines = [
        f"<b>Health · {escape(account.display_name)}</b>",
        "",
        SEPARATOR,
        "",
    ]
    for component in health.components:
        icon = "🟢" if component.healthy else "🔴"
        lines.extend([component.label, f"{icon} {component.points}/{component.maximum}"])
        if component.reason:
            lines.append(escape(component.reason))
        lines.append("")
    session_icon = "🟢" if account.session_connected else "🔴"
    lines.extend(
        [
            "Сессия",
            session_icon,
            "",
            "Последняя проверка",
            format_datetime(
                max(
                    (
                        value
                        for value in (
                            account.proxy_last_checked_at,
                            account.session_last_checked_at,
                        )
                        if value is not None
                    ),
                    default=None,
                )
            ),
            "",
            "Overall",
            f"{health_indicator(health.score)} {health.score}%",
            "",
            SEPARATOR,
        ]
    )
    return "\n".join(lines)


def format_proxy_card(account: AdvertisingAccount) -> str:
    status = (
        "⚪ Отключён"
        if not account.proxy_enabled
        else {
            "working": "🟢 Работает",
            "failed": "🔴 Не работает",
            "unknown": "🟡 Не проверен",
        }.get(account.proxy_status or "unknown", "🟡 Не проверен")
    )
    address = f"{mask_proxy_host(account.proxy_host)}:{account.proxy_port or '—'}"
    latency = (
        f"{account.proxy_latency_ms} ms"
        if account.proxy_latency_ms is not None
        else "—"
    )
    return (
        "<b>Прокси</b>\n\n"
        f"{SEPARATOR}\n\n"
        f"Статус\n{status}\n\n"
        f"Тип\n{escape(account.proxy_type or 'Не определён')}\n\n"
        f"Адрес\n{escape(address)}\n\n"
        f"Задержка\n{latency}\n\n"
        f"Последняя проверка\n{format_datetime(account.proxy_last_checked_at, True)}\n\n"
        f"Последний успех\n{format_datetime(account.proxy_last_success_at, True)}\n\n"
        f"Последняя ошибка\n{escape(account.proxy_last_error or '—')}\n\n"
        f"{SEPARATOR}"
    )


def format_proxy_history(
    account: AdvertisingAccount,
    records: list[ProxyCheckHistory],
) -> str:
    lines = [
        f"<b>История прокси · {escape(account.display_name)}</b>",
        "",
        SEPARATOR,
        "",
    ]
    if not records:
        lines.extend(["Проверок пока нет.", ""])
    for record in records:
        icon = "🟢" if record.status == "working" else "🔴"
        value = f"{record.latency_ms} ms" if record.latency_ms is not None else "—"
        lines.extend([format_datetime(record.checked_at, True), f"{icon} {value}"])
        if record.error:
            lines.append(escape(record.error))
        lines.append("")
    lines.append(SEPARATOR)
    return "\n".join(lines)


def format_dashboard_card(
    stats: dict,
    account_health: list[tuple[AdvertisingAccount, AccountHealth]],
    overall_score: int,
) -> str:
    healthy = sum(health.score >= 90 for _, health in account_health)
    attention = len(account_health) - healthy
    lines = [
        "<b>Dashboard</b>",
        "",
        SEPARATOR,
        "",
        "<b>Аккаунты</b>",
        f"{len(account_health)} всего",
        f"{healthy} healthy",
        f"{attention} требуют внимания",
        "",
        "<b>Кампании</b>",
        f"{stats['chats']['active']} активных чатов",
        f"{stats['templates']['active']} шаблонов",
        "",
        "<b>Прокси</b>",
        f"{stats['proxy']['online']} online",
        f"{stats['proxy']['offline']} offline",
        "",
        "<b>Активность сегодня</b>",
        f"{stats['sends']['today']} отправок",
        f"{stats['sends']['errors_today']} ошибок",
        "",
        SEPARATOR,
        "",
        "<b>System Health</b>",
        f"{health_indicator(overall_score)} {overall_score}%",
        "",
        "<b>Accounts Health</b>",
        "",
        SEPARATOR,
        "",
    ]
    for account, health in account_health:
        lines.extend(
            [
                escape(account.display_name),
                f"{health_indicator(health.score)} {health.score}%",
                "",
            ]
        )
    lines.append(SEPARATOR)
    return "\n".join(lines)
