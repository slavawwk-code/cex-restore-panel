import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.database.models import AdvertisingAccount, ProxyCheckHistory
from app.services.account_health import update_persisted_health
from app.services.device_identity import proxy_diagnostic_identity_kwargs
from app.telethon.config import get_api_credentials
from app.telethon.proxy import build_telethon_proxy_config

logger = logging.getLogger(__name__)

PROXY_TYPES = {"SOCKS5", "SOCKS4", "HTTP"}
AUTO_DETECTION_ORDER = ("SOCKS5", "HTTP", "SOCKS4")


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ProxyConfigurationError(ValueError):
    """Raised when proxy settings are incomplete or invalid."""


class ProxyStringParseError(ProxyConfigurationError):
    """Raised when a pasted proxy string cannot be recognized."""


@dataclass(frozen=True, repr=False)
class ParsedProxy:
    """Validated proxy data parsed from a single operator message."""

    proxy_type: str | None
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    candidate_types: tuple[str, ...] = AUTO_DETECTION_ORDER


@dataclass(frozen=True)
class ProxyTestResult:
    """Result of checking one proxy protocol against Telegram."""

    proxy_type: str
    success: bool
    error: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class ProxyDetectionResult:
    """Ordered results of proxy protocol detection."""

    success: bool
    detected_type: str | None
    attempts: tuple[ProxyTestResult, ...]


def parse_proxy_string(value: str) -> ParsedProxy:
    """Parse common proxy representations without exposing credentials."""
    raw_value = value.strip()
    if not raw_value or any(char.isspace() for char in raw_value):
        raise ProxyStringParseError("Строка прокси пустая или содержит пробелы")

    try:
        if "://" in raw_value:
            parsed = _parse_proxy_url(raw_value)
        elif "@" in raw_value:
            parsed = _parse_authenticated_proxy(raw_value)
        else:
            parsed = _parse_colon_proxy(raw_value)

        validate_proxy_settings(
            parsed.candidate_types[0],
            parsed.host,
            parsed.port,
            parsed.username,
            parsed.password,
        )
        return parsed
    except ProxyStringParseError:
        raise
    except (TypeError, ValueError) as error:
        raise ProxyStringParseError("Неверный адрес или порт прокси") from error


def _parse_proxy_url(value: str) -> ParsedProxy:
    parsed = urlsplit(value)
    proxy_type = {
        "socks5": "SOCKS5",
        "socks4": "SOCKS4",
        "http": "HTTP",
        # Telethon uses HTTP CONNECT for proxy URLs with either HTTP scheme.
        "https": "HTTP",
    }.get(parsed.scheme.lower())
    if not proxy_type:
        raise ProxyStringParseError("Поддерживаются только http, https, socks4 и socks5")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ProxyStringParseError("В строке прокси не должно быть пути или параметров")

    try:
        port = parsed.port
    except ValueError as error:
        fallback = _parse_scheme_host_port_credentials(parsed.netloc, proxy_type)
        if fallback is not None:
            return fallback
        raise ProxyStringParseError("Указан неверный порт прокси") from error
    if not parsed.hostname or port is None:
        raise ProxyStringParseError("Не удалось найти хост и порт прокси")

    username = unquote(parsed.username) if parsed.username is not None else None
    password = unquote(parsed.password) if parsed.password is not None else None
    _validate_credentials_pair(username, password)
    return ParsedProxy(
        proxy_type=proxy_type,
        host=parsed.hostname,
        port=port,
        username=username,
        password=password,
        candidate_types=(proxy_type,),
    )


def _parse_scheme_host_port_credentials(
    netloc: str,
    proxy_type: str,
) -> ParsedProxy | None:
    """Parse seller format scheme://host:port:login:password."""
    if "@" in netloc or netloc.startswith("["):
        return None
    parts = netloc.split(":")
    if len(parts) < 4:
        return None
    host, port_text, username = parts[:3]
    password = ":".join(parts[3:])
    try:
        port = int(port_text)
    except ValueError as error:
        raise ProxyStringParseError("Указан неверный порт прокси") from error
    username = unquote(username)
    password = unquote(password)
    _validate_credentials_pair(username, password)
    return ParsedProxy(
        proxy_type=proxy_type,
        host=host,
        port=port,
        username=username,
        password=password,
        candidate_types=(proxy_type,),
    )


def _parse_authenticated_proxy(value: str) -> ParsedProxy:
    credentials, address = value.rsplit("@", 1)
    if ":" not in credentials:
        raise ProxyStringParseError("Укажите логин и пароль через двоеточие")
    username, password = credentials.split(":", 1)
    _validate_credentials_pair(username, password)
    host, port = _parse_host_port(address)
    return ParsedProxy(
        proxy_type=None,
        host=host,
        port=port,
        username=username,
        password=password,
    )


def _parse_colon_proxy(value: str) -> ParsedProxy:
    if value.startswith("["):
        host, port = _parse_host_port(value)
        return ParsedProxy(proxy_type=None, host=host, port=port)

    parts = value.split(":")
    if len(parts) == 2:
        host, port_text = parts
        return ParsedProxy(proxy_type=None, host=host, port=int(port_text))
    if len(parts) >= 4:
        host, port_text, username = parts[:3]
        password = ":".join(parts[3:])
        _validate_credentials_pair(username, password)
        return ParsedProxy(
            proxy_type=None,
            host=host,
            port=int(port_text),
            username=username,
            password=password,
        )
    raise ProxyStringParseError("Количество частей в строке прокси не распознано")


def _parse_host_port(value: str) -> tuple[str, int]:
    parsed = urlsplit(f"//{value}")
    try:
        port = parsed.port
    except ValueError as error:
        raise ProxyStringParseError("Указан неверный порт прокси") from error
    if not parsed.hostname or port is None:
        raise ProxyStringParseError("Не удалось найти хост и порт прокси")
    return parsed.hostname, port


def _validate_credentials_pair(
    username: str | None, password: str | None
) -> None:
    if bool(username) != bool(password):
        raise ProxyStringParseError("Логин и пароль должны быть указаны вместе")


def validate_proxy_settings(
    proxy_type: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Validate operator-provided proxy settings."""
    if proxy_type not in PROXY_TYPES:
        raise ProxyConfigurationError("Неподдерживаемый тип прокси")
    if not host or len(host) > 255 or any(char.isspace() for char in host):
        raise ProxyConfigurationError("Укажите корректный хост прокси")
    if port < 1 or port > 65535:
        raise ProxyConfigurationError("Порт должен быть от 1 до 65535")
    if username and len(username) > 255:
        raise ProxyConfigurationError("Логин прокси слишком длинный")
    if password and len(password) > 255:
        raise ProxyConfigurationError("Пароль прокси слишком длинный")


def configure_proxy(
    session: Session,
    account: AdvertisingAccount,
    proxy_type: str,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
) -> None:
    """Save and enable proxy settings for an advertising account."""
    normalized_type = proxy_type.upper()
    normalized_host = host.strip()
    normalized_username = username.strip() if username else None
    normalized_password = password if password else None
    validate_proxy_settings(
        normalized_type,
        normalized_host,
        port,
        normalized_username,
        normalized_password,
    )

    account.proxy_type = normalized_type
    account.proxy_host = normalized_host
    account.proxy_port = port
    account.proxy_username = normalized_username
    account.proxy_password = normalized_password
    account.proxy_enabled = True
    account.proxy_last_check_at = None
    account.proxy_last_check_success = None
    account.proxy_status = "unknown"
    account.proxy_last_checked_at = None
    account.proxy_last_success_at = None
    account.proxy_last_error = None
    account.proxy_latency_ms = None
    account.proxy_detected_type = None
    account.proxy_diagnostics = None
    update_persisted_health(session, account)
    session.commit()
    logger.info("Proxy configured for account %s", account.id)


def disable_proxy(session: Session, account: AdvertisingAccount) -> None:
    """Disable an account proxy without deleting its saved settings."""
    account.proxy_enabled = False
    update_persisted_health(session, account)
    session.commit()
    logger.info("Proxy disabled for account %s", account.id)


async def run_fast_proxy_check(
    session: Session,
    account: AdvertisingAccount,
    timeout_seconds: int = 6,
) -> ProxyTestResult:
    """Check Telegram through the currently saved proxy type only."""
    if not account.proxy_enabled:
        return ProxyTestResult("", False, "Прокси отключён")
    if not account.proxy_type:
        return ProxyTestResult("", False, "Тип прокси ещё не определён")

    config = ParsedProxy(
        proxy_type=account.proxy_type,
        host=account.proxy_host or "",
        port=account.proxy_port or 0,
        username=account.proxy_username,
        password=account.proxy_password,
        candidate_types=(account.proxy_type or "",),
    )
    result = await test_proxy_with_type(
        config,
        account.proxy_type,
        timeout_seconds=timeout_seconds,
    )
    _apply_proxy_test_status(session, account, result)
    if result.success:
        logger.info("Fast proxy test succeeded for account %s", account.id)
    else:
        logger.warning(
            "Fast proxy test failed for account %s: %s",
            account.id,
            result.error,
        )
    return result


async def test_proxy(
    session: Session,
    account: AdvertisingAccount,
    timeout_seconds: int = 6,
) -> tuple[bool, str]:
    """Backward-compatible wrapper around the fast proxy check."""
    result = await run_fast_proxy_check(session, account, timeout_seconds)
    return result.success, result.error or "Telegram доступен через прокси"


async def test_proxy_with_type(
    proxy_config: ParsedProxy,
    proxy_type: str,
    timeout_seconds: int = 15,
) -> ProxyTestResult:
    """Verify Telegram RPC availability through one Telethon proxy type."""
    started_at = time.perf_counter()
    try:
        validate_proxy_settings(
            proxy_type,
            proxy_config.host,
            proxy_config.port,
            proxy_config.username,
            proxy_config.password,
        )
        api_id, api_hash = get_api_credentials()
        telethon_proxy = build_telethon_proxy_config(
            proxy_type,
            proxy_config.host,
            proxy_config.port,
            proxy_config.username,
            proxy_config.password,
        )
        client = TelegramClient(
            StringSession(),
            api_id,
            api_hash,
            proxy=telethon_proxy,
            connection_retries=1,
            request_retries=1,
            timeout=timeout_seconds,
            **proxy_diagnostic_identity_kwargs(),
        )
        try:
            async def verify_telegram() -> None:
                await client.connect()
                if not client.is_connected():
                    raise ConnectionError("соединение с Telegram не установлено")
                # This performs a Telegram RPC request and works for both
                # authorized and not-yet-authorized sessions.
                await client.is_user_authorized()

            await asyncio.wait_for(verify_telegram(), timeout=timeout_seconds)
        finally:
            await client.disconnect()
        latency_ms = max(1, round((time.perf_counter() - started_at) * 1000))
        return ProxyTestResult(
            proxy_type=proxy_type,
            success=True,
            latency_ms=latency_ms,
        )
    except TypeError as error:
        logger.exception(
            "proxy_telegram_check_type_error proxy_type=%s host=%s port=%s "
            "has_username=%s has_password=%s error_repr=%r",
            proxy_type,
            proxy_config.host,
            proxy_config.port,
            bool(proxy_config.username),
            bool(proxy_config.password),
            error,
        )
        return ProxyTestResult(
            proxy_type=proxy_type,
            success=False,
            error=_format_proxy_error(error),
            latency_ms=None,
        )
    except Exception as error:
        return ProxyTestResult(
            proxy_type=proxy_type,
            success=False,
            error=_format_proxy_error(error),
            latency_ms=None,
        )


async def detect_working_proxy_type(
    proxy_config: ParsedProxy,
    candidate_types: tuple[str, ...] | None = None,
    timeout_seconds: int = 15,
) -> ProxyDetectionResult:
    """Try proxy protocols in order and stop at the first Telegram success."""
    types_to_test = candidate_types or proxy_config.candidate_types
    attempts: list[ProxyTestResult] = []
    for proxy_type in types_to_test:
        result = await test_proxy_with_type(
            proxy_config, proxy_type, timeout_seconds=timeout_seconds
        )
        attempts.append(result)
        if result.success:
            return ProxyDetectionResult(
                success=True,
                detected_type=proxy_type,
                attempts=tuple(attempts),
            )
    return ProxyDetectionResult(
        success=False,
        detected_type=None,
        attempts=tuple(attempts),
    )


async def run_full_proxy_diagnostics(
    session: Session,
    account: AdvertisingAccount,
    timeout_seconds: int = 15,
) -> ProxyDetectionResult:
    """Run saved proxy diagnostics using explicit or auto-detected type policy."""
    if not account.proxy_enabled or not account.proxy_host or not account.proxy_port:
        return ProxyDetectionResult(
            success=False,
            detected_type=None,
            attempts=(ProxyTestResult("", False, "Прокси не настроен"),),
        )

    candidate_types = (
        AUTO_DETECTION_ORDER
        if account.proxy_detected_type
        else ((account.proxy_type,) if account.proxy_type else AUTO_DETECTION_ORDER)
    )
    config = ParsedProxy(
        proxy_type=None if len(candidate_types) > 1 else candidate_types[0],
        host=account.proxy_host,
        port=account.proxy_port,
        username=account.proxy_username,
        password=account.proxy_password,
        candidate_types=candidate_types,
    )
    detection = await detect_working_proxy_type(
        config,
        candidate_types=candidate_types,
        timeout_seconds=timeout_seconds,
    )
    account.proxy_diagnostics = _serialize_diagnostics(detection)
    if detection.success and detection.detected_type:
        account.proxy_type = detection.detected_type
        account.proxy_detected_type = (
            detection.detected_type if len(candidate_types) > 1 else None
        )
        _apply_proxy_test_status(session, account, detection.attempts[-1])
    else:
        _apply_proxy_test_status(session, account, detection.attempts[-1])
    return detection


def _apply_proxy_test_status(
    session: Session,
    account: AdvertisingAccount,
    result: ProxyTestResult,
) -> None:
    now = _utc_now()
    account.proxy_last_check_at = now
    account.proxy_last_check_success = result.success
    account.proxy_last_checked_at = now
    if result.success:
        account.proxy_status = "working"
        account.proxy_last_success_at = now
        account.proxy_last_error = None
        account.proxy_latency_ms = result.latency_ms
    else:
        account.proxy_status = "failed"
        account.proxy_last_error = result.error or "неизвестная ошибка"
        account.proxy_latency_ms = None
    _record_proxy_check(session, account, result, now)
    update_persisted_health(session, account)
    session.commit()


def _record_proxy_check(
    session: Session,
    account: AdvertisingAccount,
    result: ProxyTestResult,
    checked_at: datetime,
) -> None:
    """Store one safe health record and retain only the latest 20 per account."""
    session.add(
        ProxyCheckHistory(
            account_id=account.id,
            checked_at=checked_at,
            status="working" if result.success else "failed",
            latency_ms=result.latency_ms if result.success else None,
            error=None if result.success else (result.error or "неизвестная ошибка"),
        )
    )
    session.flush()
    stale_records = (
        session.query(ProxyCheckHistory)
        .filter(ProxyCheckHistory.account_id == account.id)
        .order_by(
            ProxyCheckHistory.checked_at.desc(),
            ProxyCheckHistory.id.desc(),
        )
        .offset(20)
        .all()
    )
    for record in stale_records:
        session.delete(record)


def get_proxy_history(
    session: Session, account_id: int, limit: int = 20
) -> list[ProxyCheckHistory]:
    """Return recent proxy checks without exposing proxy credentials."""
    return (
        session.query(ProxyCheckHistory)
        .filter(ProxyCheckHistory.account_id == account_id)
        .order_by(
            ProxyCheckHistory.checked_at.desc(),
            ProxyCheckHistory.id.desc(),
        )
        .limit(min(max(limit, 1), 20))
        .all()
    )


def _serialize_diagnostics(detection: ProxyDetectionResult) -> str:
    return json.dumps(
        [
            {
                "proxy_type": attempt.proxy_type,
                "success": attempt.success,
                "error": attempt.error,
                "latency_ms": attempt.latency_ms,
            }
            for attempt in detection.attempts
        ],
        ensure_ascii=False,
    )


def save_detected_proxy(
    session: Session,
    account: AdvertisingAccount,
    proxy_config: ParsedProxy,
    detection: ProxyDetectionResult,
) -> None:
    """Persist a successfully detected proxy type and test status."""
    if not detection.success or not detection.detected_type:
        raise ProxyConfigurationError("Рабочий тип прокси не определён")
    configure_proxy(
        session,
        account,
        detection.detected_type,
        proxy_config.host,
        proxy_config.port,
        proxy_config.username,
        proxy_config.password,
    )
    account.proxy_detected_type = (
        detection.detected_type if proxy_config.proxy_type is None else None
    )
    account.proxy_diagnostics = _serialize_diagnostics(detection)
    _apply_proxy_test_status(session, account, detection.attempts[-1])


def format_proxy_confirmation(proxy_config: ParsedProxy) -> str:
    """Format parsed proxy data with a permanently masked password."""
    type_label = proxy_config.proxy_type or "Определить автоматически"
    password_label = "••••••••" if proxy_config.password else "не задан"
    return (
        "Прокси распознан\n\n"
        f"IP:\n{proxy_config.host}\n\n"
        f"Порт:\n{proxy_config.port}\n\n"
        f"Логин:\n{proxy_config.username or 'не задан'}\n\n"
        f"Пароль:\n{password_label}\n\n"
        f"Тип:\n{type_label}\n\n"
        "Все верно?"
    )


def format_proxy_detection_failure(detection: ProxyDetectionResult) -> str:
    """Format safe per-type diagnostics without proxy credentials."""
    lines = [
        "🔴 Прокси не прошёл проверку Telegram",
        "",
        "Проверенные типы:",
        "",
    ]
    for attempt in detection.attempts:
        lines.append(
            f"{attempt.proxy_type}: {attempt.error or 'неизвестная ошибка'}"
        )
    lines.extend(
        [
            "",
            "Этот прокси может работать для сайтов, но быть недоступным для Telegram/Telethon.",
        ]
    )
    return "\n".join(lines)


def format_proxy_diagnostics(detection: ProxyDetectionResult) -> str:
    """Format per-type full diagnostic results."""
    lines = ["Результаты диагностики", ""]
    for attempt in detection.attempts:
        if attempt.success:
            latency = (
                f", {attempt.latency_ms} мс" if attempt.latency_ms is not None else ""
            )
            lines.append(f"{attempt.proxy_type}: 🟢 работает{latency}")
        else:
            lines.append(
                f"{attempt.proxy_type}: 🔴 {attempt.error or 'неизвестная ошибка'}"
            )
    return "\n".join(lines)


def format_proxy_status_card(account: AdvertisingAccount) -> str:
    """Build the operator proxy card without exposing credentials."""
    from app.ui.cards import format_proxy_card

    return format_proxy_card(account)


def format_proxy_timestamp(value: datetime) -> str:
    """Render UTC database timestamps in the configured operator timezone."""
    timezone_name = os.getenv("TZ", "Europe/Moscow")
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = UTC
    aware_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware_value.astimezone(local_timezone).strftime("%d.%m.%Y %H:%M")


def _format_proxy_error(error: Exception) -> str:
    """Convert low-level connection failures into safe operator diagnostics."""
    raw_text = str(error).strip()
    error_text = raw_text.lower()
    if isinstance(error, asyncio.TimeoutError) or "timed out" in error_text:
        return "Прокси не ответил вовремя"
    if "authentication" in error_text or "auth" in error_text:
        return "Прокси отклонил логин или пароль"
    if "refused" in error_text:
        return "Прокси отклонил соединение"
    if "name or service" in error_text or "nodename" in error_text:
        return "Не удалось найти хост прокси"
    if isinstance(error, ProxyConfigurationError):
        return str(error)
    if isinstance(error, TypeError):
        reason = raw_text or repr(error)
        return f"Ошибка формата прокси для Telethon: {reason}"
    if raw_text:
        return f"Не удалось подключиться через прокси: {type(error).__name__}: {raw_text}"
    return f"Не удалось подключиться через прокси: {type(error).__name__}"
