import logging
import os
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
from telethon.errors.rpc_error_list import (
    PhoneCodeEmptySentError,
    PhoneUnconfirmedError,
)
from app.database.models import AdvertisingAccount

logger = logging.getLogger(__name__)

SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")


class TelethonAuthError(Exception):
    """Base exception for Telethon auth errors."""

    pass


def _get_session_path(account: AdvertisingAccount) -> str:
    """Get full path to session file."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return os.path.join(SESSIONS_DIR, account.telethon_session)


async def send_login_code(account: AdvertisingAccount) -> str:
    """
    Send login code to phone number.
    Returns phone number hash (needed for code verification).
    """
    if not account.phone_number:
        raise TelethonAuthError("Phone number not set for this account")

    try:
        session_path = _get_session_path(account)
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        # Request code send
        phone_code_hash = None
        try:
            result = await client.send_code_request(account.phone_number)
            phone_code_hash = result.phone_code_hash
        except PhoneNumberInvalidError:
            raise TelethonAuthError("Invalid phone number format")
        except PhoneUnconfirmedError:
            raise TelethonAuthError("Phone number not confirmed on Telegram")
        except FloodWaitError as e:
            raise TelethonAuthError(f"Too many requests. Wait {e.seconds} seconds")
        except RPCError as e:
            raise TelethonAuthError(f"Telegram error: {str(e)}")

        logger.info(f"Login code sent to {account.phone_number} for account {account.id}")

        await client.disconnect()
        return phone_code_hash

    except TelethonAuthError:
        raise
    except Exception as e:
        logger.error(f"Error sending login code for account {account.id}: {e}", exc_info=True)
        raise TelethonAuthError(f"Failed to send login code: {str(e)}")


async def sign_in_with_code(
    account: AdvertisingAccount, phone_code: str, phone_code_hash: str
) -> bool:
    """
    Sign in with phone code.
    Returns True if successful, raises exception otherwise.
    May raise SessionPasswordNeededError if 2FA password is required.
    """
    if not phone_code or len(phone_code) < 4:
        raise TelethonAuthError("Invalid code format")

    try:
        session_path = _get_session_path(account)
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        try:
            user = await client.sign_in(account.phone_number, phone_code, phone_code_hash=phone_code_hash)
            logger.info(f"User signed in: {user.first_name} (ID: {user.id}) for account {account.id}")
        except SessionPasswordNeededError:
            await client.disconnect()
            raise  # Re-raise to let handler know 2FA is needed
        except PhoneCodeInvalidError:
            raise TelethonAuthError("Invalid code. Please try again.")
        except PhoneCodeExpiredError:
            raise TelethonAuthError("Code expired. Please request a new one.")
        except FloodWaitError as e:
            raise TelethonAuthError(f"Too many attempts. Wait {e.seconds} seconds")
        except RPCError as e:
            raise TelethonAuthError(f"Telegram error: {str(e)}")

        await client.disconnect()
        return True

    except (TelethonAuthError, SessionPasswordNeededError):
        raise
    except Exception as e:
        logger.error(f"Error signing in for account {account.id}: {e}", exc_info=True)
        raise TelethonAuthError(f"Sign in failed: {str(e)}")


async def sign_in_with_password(account: AdvertisingAccount, password: str) -> bool:
    """
    Complete 2FA sign in with password.
    Returns True if successful.
    """
    if not password:
        raise TelethonAuthError("Password cannot be empty")

    try:
        session_path = _get_session_path(account)
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        try:
            user = await client.sign_in(password=password)
            logger.info(f"2FA authentication successful for account {account.id}")
        except Exception as e:
            raise TelethonAuthError(f"Authentication failed: {str(e)}")

        await client.disconnect()
        return True

    except TelethonAuthError:
        raise
    except Exception as e:
        logger.error(f"Error during 2FA for account {account.id}: {e}", exc_info=True)
        raise TelethonAuthError(f"2FA failed: {str(e)}")


async def check_session_status(session: Session, account: AdvertisingAccount) -> dict:
    """
    Check if session is valid and authorized.
    Update session status fields in database.
    Returns dict with status information.
    """
    try:
        session_path = _get_session_path(account)

        # Check if session file exists
        if not os.path.exists(session_path + ".session"):
            account.session_connected = False
            account.session_user_id = None
            account.session_username = None
            account.session_last_checked_at = datetime.utcnow()
            session.commit()
            logger.info(f"Session file not found for account {account.id}")
            return {
                "connected": False,
                "reason": "No session file",
                "user_id": None,
                "username": None,
            }

        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        is_authorized = await client.is_user_authorized()

        if is_authorized:
            user = await client.get_me()
            account.session_connected = True
            account.session_user_id = str(user.id)
            account.session_username = user.username or f"ID: {user.id}"
            account.session_last_checked_at = datetime.utcnow()
            session.commit()
            await client.disconnect()

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
            session.commit()
            await client.disconnect()

            logger.warning(f"Session not authorized for account {account.id}")
            return {
                "connected": False,
                "reason": "Session not authorized",
                "user_id": None,
                "username": None,
            }

    except Exception as e:
        logger.error(f"Error checking session status for account {account.id}: {e}", exc_info=True)
        account.session_connected = False
        account.session_last_checked_at = datetime.utcnow()
        session.commit()

        return {
            "connected": False,
            "reason": f"Error: {str(e)}",
            "user_id": None,
            "username": None,
        }


async def disconnect_session(session: Session, account: AdvertisingAccount, delete_file: bool = False) -> bool:
    """
    Disconnect session and optionally delete/rename session file.
    Update database to mark as disconnected.
    """
    try:
        session_path = _get_session_path(account)

        # Update database
        account.session_connected = False
        account.session_user_id = None
        account.session_username = None
        account.session_last_checked_at = datetime.utcnow()
        session.commit()

        # Try to disconnect client
        try:
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.connect()
            await client.log_out()
            await client.disconnect()
            logger.info(f"Client logged out for account {account.id}")
        except Exception as e:
            logger.warning(f"Error logging out client for account {account.id}: {e}")

        # Handle session file
        if delete_file:
            session_file = session_path + ".session"
            if os.path.exists(session_file):
                os.remove(session_file)
                logger.info(f"Session file deleted for account {account.id}")

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
