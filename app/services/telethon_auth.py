import logging
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneNumberInvalidError,
    RPCError,
)
from app.database.models import AdvertisingAccount
from app.services.account_health import update_persisted_health
from app.services.account_sessions import (
    create_account_client,
    resolve_session_source,
)

logger = logging.getLogger(__name__)

class TelethonAuthError(Exception):
    """Base exception for Telethon auth errors."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _create_client(account: AdvertisingAccount) -> TelegramClient:
    """Create a client using file → string session priority."""
    return create_account_client(account)


def _create_login_client(account: AdvertisingAccount) -> TelegramClient:
    """Create a file-backed client for phone-code login."""
    return create_account_client(account, for_login=True)


def _describe_delivery(sent_code) -> str:
    """Describe Telegram's selected login-code delivery channel."""
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


async def send_login_code(account: AdvertisingAccount) -> dict:
    """
    Send login code to phone number.
    Return the phone code hash and Telegram-selected delivery information.
    """
    if not account.phone_number:
        raise TelethonAuthError("Для аккаунта не указан номер телефона")

    client = None
    try:
        client = _create_login_client(account)
        await asyncio.wait_for(client.connect(), timeout=15)
        if await client.is_user_authorized():
            user = await client.get_me()
            logger.info("Existing session is authorized for account %s", account.id)
            return {
                "already_authorized": True,
                "user_id": str(user.id),
                "username": user.username,
            }

        try:
            result = await client.send_code_request(account.phone_number)
        except PhoneNumberInvalidError:
            raise TelethonAuthError("Telegram отклонил формат номера телефона")
        except FloodWaitError as e:
            raise TelethonAuthError(
                f"Слишком много запросов. Повторите через {e.seconds} сек.",
                retry_after=e.seconds,
            )
        except RPCError as e:
            raise TelethonAuthError(
                f"Telegram отклонил запрос ({type(e).__name__})"
            )

        logger.info("Login code requested for account %s", account.id)
        return {
            "already_authorized": False,
            "phone_code_hash": result.phone_code_hash,
            "delivery": _describe_delivery(result),
            "timeout": getattr(result, "timeout", None),
        }

    except TelethonAuthError:
        raise
    except (asyncio.TimeoutError, ConnectionError, OSError) as e:
        route = " через настроенный прокси" if account.proxy_enabled else ""
        logger.warning(
            "Connection failed while requesting login code for account %s: %s",
            account.id,
            type(e).__name__,
        )
        raise TelethonAuthError(
            f"Не удалось подключиться к Telegram{route}. Проверьте сеть и прокси."
        ) from e
    except Exception as e:
        logger.error("Error sending login code for account %s", account.id, exc_info=True)
        raise TelethonAuthError(
            f"Не удалось запросить код ({type(e).__name__})"
        ) from e
    finally:
        if client is not None:
            await client.disconnect()


async def sign_in_with_code(
    account: AdvertisingAccount, phone_code: str, phone_code_hash: str
) -> bool:
    """
    Sign in with phone code.
    Returns True if successful, raises exception otherwise.
    May raise SessionPasswordNeededError if 2FA password is required.
    """
    if not phone_code or len(phone_code) < 4:
        raise TelethonAuthError("Неверный формат кода")

    client = None
    try:
        client = _create_login_client(account)
        await asyncio.wait_for(client.connect(), timeout=15)

        try:
            await client.sign_in(account.phone_number, phone_code, phone_code_hash=phone_code_hash)
            logger.info("User signed in for account %s", account.id)
        except SessionPasswordNeededError:
            raise
        except PhoneCodeInvalidError:
            raise TelethonAuthError("Telegram отклонил код. Проверьте цифры и повторите.")
        except PhoneCodeExpiredError:
            raise TelethonAuthError("Срок действия кода истёк. Запросите новый код.")
        except FloodWaitError as e:
            raise TelethonAuthError(
                f"Слишком много попыток. Повторите через {e.seconds} сек.",
                retry_after=e.seconds,
            )
        except RPCError as e:
            raise TelethonAuthError(
                f"Telegram отклонил авторизацию ({type(e).__name__})"
            )

        return True

    except (TelethonAuthError, SessionPasswordNeededError):
        raise
    except Exception as e:
        logger.error("Error signing in for account %s", account.id, exc_info=True)
        raise TelethonAuthError(f"Ошибка авторизации ({type(e).__name__})") from e
    finally:
        if client is not None:
            await client.disconnect()


async def sign_in_with_password(account: AdvertisingAccount, password: str) -> bool:
    """
    Complete 2FA sign in with password.
    Returns True if successful.
    """
    if not password:
        raise TelethonAuthError("Пароль не может быть пустым")

    client = None
    try:
        client = _create_login_client(account)
        await asyncio.wait_for(client.connect(), timeout=15)

        try:
            await client.sign_in(password=password)
            logger.info("2FA authentication successful for account %s", account.id)
        except Exception as e:
            raise TelethonAuthError(
                f"Telegram отклонил пароль ({type(e).__name__})"
            ) from e

        return True

    except TelethonAuthError:
        raise
    except Exception as e:
        logger.error("Error during 2FA for account %s", account.id, exc_info=True)
        raise TelethonAuthError(f"Ошибка проверки 2FA ({type(e).__name__})") from e
    finally:
        if client is not None:
            await client.disconnect()


async def check_session_status(session: Session, account: AdvertisingAccount) -> dict:
    """
    Check if session is valid and authorized.
    Update session status fields in database.
    Returns dict with status information.
    """
    client = None
    try:
        resolution = resolve_session_source(account)
        if resolution is None:
            account.session_connected = False
            account.session_user_id = None
            account.session_username = None
            account.session_last_checked_at = datetime.utcnow()
            account.auth_status = "unverified"
            account.last_auth_error = "Сессия не настроена"
            update_persisted_health(session, account)
            session.commit()
            logger.info("Session not configured for account %s", account.id)
            return {
                "connected": False,
                "reason": "File/StringSession не настроена",
                "user_id": None,
                "username": None,
            }

        client = _create_client(account)
        await asyncio.wait_for(client.connect(), timeout=15)

        is_authorized = await client.is_user_authorized()

        if is_authorized:
            user = await client.get_me()
            account.session_connected = True
            if not account.session_connected_at:
                account.session_connected_at = datetime.utcnow()
            account.session_user_id = str(user.id)
            account.session_username = user.username or f"ID: {user.id}"
            account.session_last_checked_at = datetime.utcnow()
            account.auth_status = "active"
            account.last_auth_error = None
            account.last_error = None
            update_persisted_health(session, account)
            session.commit()
            logger.info(f"Session verified for account {account.id}: {user.username or user.id}")
            return {
                "connected": True,
                "user_id": str(user.id),
                "username": user.username,
                "first_name": user.first_name,
            }
        else:
            account.session_connected = False
            account.session_user_id = None
            account.session_username = None
            account.session_last_checked_at = datetime.utcnow()
            account.auth_status = "unverified"
            account.last_auth_error = "Сессия не авторизована"
            update_persisted_health(session, account)
            session.commit()
            logger.warning(f"Session not authorized for account {account.id}")
            return {
                "connected": False,
                "reason": "Сессия не авторизована",
                "user_id": None,
                "username": None,
            }

    except Exception as e:
        logger.error(f"Error checking session status for account {account.id}: {e}", exc_info=True)
        account.session_connected = False
        account.session_last_checked_at = datetime.utcnow()
        account.auth_status = (
            "banned" if "banned" in type(e).__name__.lower() else "error"
        )
        account.last_auth_error = f"{type(e).__name__}: проверка сессии не пройдена"
        account.last_error = account.last_auth_error
        update_persisted_health(session, account)
        session.commit()

        return {
            "connected": False,
            "reason": f"Ошибка проверки: {type(e).__name__}",
            "user_id": None,
            "username": None,
        }
    finally:
        if client is not None:
            await client.disconnect()


async def disconnect_session(session: Session, account: AdvertisingAccount, delete_file: bool = False) -> bool:
    """
    Disconnect session and optionally delete/rename session file.
    Update database to mark as disconnected.
    """
    try:
        resolution = resolve_session_source(account)

        # Try to disconnect client
        client = None
        try:
            if resolution is not None:
                client = _create_client(account)
                await client.connect()
                await client.log_out()
                logger.info(f"Client logged out for account {account.id}")
        except Exception as e:
            logger.warning(f"Error logging out client for account {account.id}: {e}")
        finally:
            if client is not None:
                await client.disconnect()

        account.session_connected = False
        account.session_user_id = None
        account.session_username = None
        account.session_last_checked_at = datetime.utcnow()
        account.auth_status = "unverified"
        account.last_auth_error = None
        account.string_session = None

        # Handle session file
        if delete_file:
            session_file = resolution.file_path if resolution else None
            if session_file and session_file.is_file():
                session_file.unlink()
                logger.info(f"Session file deleted for account {account.id}")
            account.session_file_path = None

        update_persisted_health(session, account)
        session.commit()

        return True

    except Exception as e:
        logger.error(f"Error disconnecting session for account {account.id}: {e}", exc_info=True)
        return False


def get_session_info(account: AdvertisingAccount) -> dict:
    """Get session info for display."""
    return {
        "connected": account.session_connected,
        "user_id": account.session_user_id,
        "username": account.session_username,
        "last_checked": account.session_last_checked_at,
    }
