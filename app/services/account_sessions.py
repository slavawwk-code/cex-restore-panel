import asyncio
import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import ensure_runtime_directories, load_settings
from app.database.models import AdvertisingAccount
from app.services.account_health import update_persisted_health
from app.services.device_identity import (
    identity_telethon_kwargs,
    sanitize_telethon_identity_kwargs,
)
from app.telethon.config import get_account_api_credentials
from app.telethon.proxy import build_proxy

MAX_SESSION_FILE_BYTES = 10 * 1024 * 1024
MAX_STRING_SESSION_LENGTH = 4096


class AccountSessionError(ValueError):
    """Safe operator-facing error for account session operations."""


@dataclass(frozen=True, repr=False)
class SessionResolution:
    kind: str
    session: str | StringSession
    file_path: Path | None


def resolve_session_source(
    account: AdvertisingAccount,
    allow_new_file: bool = False,
) -> SessionResolution | None:
    """Resolve file → StringSession → new login file in strict priority order."""
    settings = load_settings(require_secrets=False)
    ensure_runtime_directories(settings)

    if account.session_file_path:
        configured_path = _safe_session_path(account.session_file_path)
        if configured_path.is_file():
            return SessionResolution("file", str(configured_path), configured_path)

    legacy_path = _safe_session_path(account.telethon_session)
    if legacy_path.is_file():
        return SessionResolution("file", str(legacy_path), legacy_path)

    if account.string_session:
        try:
            return SessionResolution(
                "string",
                StringSession(account.string_session),
                None,
            )
        except Exception as error:
            raise AccountSessionError("StringSession повреждена или имеет неверный формат") from error

    if allow_new_file:
        new_path = canonical_session_path(account)
        return SessionResolution("login", str(new_path), new_path)
    return None


def canonical_session_path(account: AdvertisingAccount) -> Path:
    if account.id is None:
        raise AccountSessionError("Аккаунт должен быть сохранён перед созданием сессии")
    ensure_runtime_directories(load_settings(require_secrets=False))
    return _safe_session_path(f"{account.id}.session")


def login_session_path(account: AdvertisingAccount) -> Path:
    """Return the file used by the phone-code login flow."""
    resolution = _resolve_login_file(account)
    if resolution.file_path is None:
        raise AccountSessionError("Не удалось определить путь session-файла")
    return resolution.file_path


def create_account_client(
    account: AdvertisingAccount,
    *,
    for_login: bool = False,
    override_session: str | StringSession | None = None,
) -> TelegramClient:
    """Create an unconnected Telethon client with account proxy and credentials."""
    if override_session is None:
        if for_login:
            resolution = _resolve_login_file(account)
        else:
            resolution = resolve_session_source(account)
        if resolution is None:
            raise AccountSessionError("Для аккаунта не настроена Telegram-сессия")
        session_value = resolution.session
    else:
        session_value = override_session

    api_id, api_hash = get_account_api_credentials(account)
    return TelegramClient(
        session_value,
        api_id,
        api_hash,
        proxy=build_proxy(account),
        connection_retries=1,
        request_retries=2,
        timeout=15,
        **sanitize_telethon_identity_kwargs(identity_telethon_kwargs(account)),
    )


async def import_session_bytes(
    db_session: Session,
    account: AdvertisingAccount,
    filename: str,
    payload: bytes,
) -> dict:
    """Validate an uploaded Telethon SQLite session before atomically saving it."""
    if not filename.lower().endswith(".session"):
        raise AccountSessionError("Загрузите файл с расширением .session")
    if not payload or len(payload) > MAX_SESSION_FILE_BYTES:
        raise AccountSessionError("Файл сессии пустой или превышает 10 МБ")
    if not payload.startswith(b"SQLite format 3\x00"):
        raise AccountSessionError("Файл не является Telethon SQLite-сессией")

    target_path = canonical_session_path(account)
    temporary_path = target_path.parent / f".import-{account.id}-{uuid4().hex}.session"
    temporary_path.write_bytes(payload)
    temporary_path.chmod(0o600)
    client = None
    try:
        _validate_sqlite_session(temporary_path)
        client = create_account_client(account, override_session=str(temporary_path))
        user = await _verify_authorized_client(client)
        await client.disconnect()
        client = None
        if target_path.exists():
            _backup_replaced_session(account, target_path)
        os.replace(temporary_path, target_path)
        target_path.chmod(0o600)
        _mark_session_active(account, target_path, user)
        update_persisted_health(db_session, account)
        db_session.commit()
        return {
            "source": "file",
            "user_id": account.session_user_id,
            "username": account.session_username,
        }
    except AccountSessionError as error:
        db_session.rollback()
        _mark_auth_error(account, error)
        update_persisted_health(db_session, account)
        db_session.commit()
        raise
    except Exception as error:
        db_session.rollback()
        _mark_auth_error(account, error)
        update_persisted_health(db_session, account)
        db_session.commit()
        raise AccountSessionError(
            f"Не удалось проверить session-файл ({type(error).__name__})"
        ) from error
    finally:
        if client is not None:
            await client.disconnect()
        temporary_path.unlink(missing_ok=True)


async def save_string_session(
    db_session: Session,
    account: AdvertisingAccount,
    value: str,
) -> dict:
    """Verify and store a StringSession as a fallback credential."""
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_STRING_SESSION_LENGTH:
        raise AccountSessionError("StringSession пустая или слишком длинная")
    try:
        string_session = StringSession(normalized)
    except Exception as error:
        raise AccountSessionError("StringSession имеет неверный формат") from error

    client = None
    try:
        client = create_account_client(account, override_session=string_session)
        user = await _verify_authorized_client(client)
        account.string_session = normalized
        account.auth_status = "active"
        account.session_connected = True
        account.session_connected_at = account.session_connected_at or _utc_now()
        account.session_last_checked_at = _utc_now()
        account.session_user_id = str(user.id)
        account.session_username = user.username or f"ID: {user.id}"
        account.last_auth_error = None
        account.last_error = None
        account.status = "active"
        update_persisted_health(db_session, account)
        db_session.commit()
        return {
            "source": "string",
            "user_id": account.session_user_id,
            "username": account.session_username,
        }
    except AccountSessionError as error:
        db_session.rollback()
        _mark_auth_error(account, error)
        update_persisted_health(db_session, account)
        db_session.commit()
        raise
    except Exception as error:
        db_session.rollback()
        _mark_auth_error(account, error)
        update_persisted_health(db_session, account)
        db_session.commit()
        raise AccountSessionError(
            f"Не удалось проверить StringSession ({type(error).__name__})"
        ) from error
    finally:
        if client is not None:
            await client.disconnect()


def finalize_login_session(
    db_session: Session,
    account: AdvertisingAccount,
) -> None:
    """Persist the canonical/legacy file path after phone-code authorization."""
    resolution = _resolve_login_file(account)
    file_path = resolution.file_path
    if file_path is None or not file_path.is_file():
        raise AccountSessionError("Файл сессии не был создан после авторизации")
    file_path.chmod(0o600)
    account.session_file_path = file_path.name
    account.auth_status = "active"
    account.session_connected = True
    account.session_connected_at = account.session_connected_at or _utc_now()
    account.session_last_checked_at = _utc_now()
    account.last_auth_error = None
    account.last_error = None
    account.status = "active"
    update_persisted_health(db_session, account)
    db_session.commit()


def record_auth_error(
    db_session: Session,
    account: AdvertisingAccount,
    error: Exception | str,
) -> None:
    """Persist a sanitized authentication failure and refresh health."""
    error_name = type(error).__name__ if isinstance(error, Exception) else "AuthError"
    account.auth_status = "banned" if "banned" in error_name.lower() else "error"
    account.session_connected = False
    account.session_last_checked_at = _utc_now()
    account.last_auth_error = f"{error_name}: авторизация не пройдена"
    account.last_error = account.last_auth_error
    update_persisted_health(db_session, account)
    db_session.commit()


def session_source_label(account: AdvertisingAccount) -> str:
    resolution = resolve_session_source(account)
    if resolution is None:
        return "не настроена"
    return "session file" if resolution.kind == "file" else "StringSession"


def session_signature(account: AdvertisingAccount) -> tuple:
    """Return a non-secret cache key that changes when session storage changes."""
    resolution = resolve_session_source(account)
    if resolution is None:
        return ("none",)
    if resolution.file_path is not None:
        stat = resolution.file_path.stat()
        return ("file", str(resolution.file_path), stat.st_mtime_ns, stat.st_size)
    digest = hashlib.sha256((account.string_session or "").encode()).hexdigest()
    return ("string", digest)


def _resolve_login_file(account: AdvertisingAccount) -> SessionResolution:
    settings = load_settings(require_secrets=False)
    ensure_runtime_directories(settings)
    if account.session_file_path:
        configured_path = _safe_session_path(account.session_file_path)
        return SessionResolution("file", str(configured_path), configured_path)
    legacy_path = _safe_session_path(account.telethon_session)
    if legacy_path.is_file():
        return SessionResolution("file", str(legacy_path), legacy_path)
    new_path = canonical_session_path(account)
    return SessionResolution("login", str(new_path), new_path)


def _safe_session_path(value: str) -> Path:
    settings = load_settings(require_secrets=False)
    session_root = settings.sessions_dir.resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = session_root / candidate
    if candidate.suffix != ".session":
        candidate = candidate.with_suffix(".session")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(session_root)
    except ValueError as error:
        raise AccountSessionError("Путь session-файла выходит за пределы sessions/") from error
    return resolved


def _validate_sqlite_session(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
    except sqlite3.DatabaseError as error:
        raise AccountSessionError("SQLite session-файл повреждён") from error
    if not integrity or integrity[0] != "ok" or "sessions" not in tables:
        raise AccountSessionError("Файл не содержит валидную Telethon-сессию")


async def _verify_authorized_client(client: TelegramClient):
    try:
        await asyncio.wait_for(client.connect(), timeout=20)
        if not await client.is_user_authorized():
            raise AccountSessionError("Telegram-сессия не авторизована")
        user = await client.get_me()
        if user is None:
            raise AccountSessionError("Telegram не вернул данные пользователя")
        return user
    except asyncio.TimeoutError as error:
        raise AccountSessionError("Telegram не ответил вовремя") from error


def _mark_session_active(account: AdvertisingAccount, path: Path, user) -> None:
    account.session_file_path = path.name
    account.auth_status = "active"
    account.session_connected = True
    account.session_connected_at = account.session_connected_at or _utc_now()
    account.session_last_checked_at = _utc_now()
    account.session_user_id = str(user.id)
    account.session_username = user.username or f"ID: {user.id}"
    account.last_auth_error = None
    account.last_error = None
    account.status = "active"


def _mark_auth_error(account: AdvertisingAccount, error: Exception) -> None:
    error_name = type(error).__name__
    account.auth_status = "banned" if "banned" in error_name.lower() else "error"
    account.session_connected = False
    account.session_last_checked_at = _utc_now()
    account.last_auth_error = f"{error_name}: проверка сессии не пройдена"
    account.last_error = account.last_auth_error


def _backup_replaced_session(account: AdvertisingAccount, source: Path) -> None:
    settings = load_settings(require_secrets=False)
    backup_dir = settings.backup_dir / "session_replacements"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    destination = backup_dir / f"account_{account.id}_{timestamp}.session"
    with sqlite3.connect(source) as source_db:
        with sqlite3.connect(destination) as target_db:
            source_db.backup(target_db)
    destination.chmod(0o600)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
