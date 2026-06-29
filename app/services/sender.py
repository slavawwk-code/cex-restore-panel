import logging
import os
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import AdvertisingAccount, Chat, Template, SendLog
from app.telethon.client import TelethonClientManager
from telethon.errors import (
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
    PeerIdInvalidError,
    SlowModeWaitError,
    RPCError,
    UnauthorizedError,
)

logger = logging.getLogger(__name__)

DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
telethon_manager = TelethonClientManager()


async def can_send_chat(account: AdvertisingAccount, chat: Chat, template: Template) -> tuple[bool, str]:
    """
    Check if a chat is eligible for sending.
    Returns (can_send, reason).
    """
    # Check account
    if not account:
        return False, "Account not found"
    if account.status != "active":
        return False, f"Account status is {account.status}, not active"
    if not account.session_connected:
        return False, "Account session not connected"

    # Check chat
    if not chat.is_active:
        return False, "Chat is disabled"
    if chat.status == "paused":
        return False, "Chat is paused"
    if chat.status == "error":
        return False, "Chat has error status"

    # Check template
    if not template:
        return False, "Template not assigned"
    if not template.is_active:
        return False, "Template is disabled"

    # Check cooldown
    if chat.cooldown_minutes < 1 or chat.cooldown_minutes > 1440:
        return False, "Chat cooldown is invalid"

    # Check if cooldown expired
    if chat.last_sent_at:
        elapsed = (datetime.utcnow() - chat.last_sent_at).total_seconds() / 60
        if elapsed < chat.cooldown_minutes:
            return False, f"Cooldown not expired ({int(chat.cooldown_minutes - elapsed)}m remaining)"

    return True, "OK"


async def simulate_send(
    account: AdvertisingAccount,
    chat: Chat,
    template: Template,
) -> dict:
    """Simulate sending a message without actually sending."""
    return {
        "success": True,
        "mode": "SIMULATION",
        "account_id": account.id,
        "chat_id": chat.id,
        "template_id": template.id,
        "telegram_message_id": None,
        "error_message": None,
    }


async def real_send(
    account: AdvertisingAccount,
    chat: Chat,
    template: Template,
) -> dict:
    """
    Send a real message via Telethon.

    This is the actual sending implementation.
    """
    try:
        # Verify session is still connected
        if not account.session_connected:
            raise UnauthorizedError("Account session not connected")

        # Get Telethon client
        client = await telethon_manager.get_client(account.telethon_session)

        if not client.is_connected():
            await client.connect()

        # Verify still authorized
        if not await client.is_user_authorized():
            raise UnauthorizedError("Client not authorized")

        # Send message
        try:
            message = await client.send_message(chat.username_or_chat_id, template.text)
            message_id = message.id

            logger.info(
                f"Message sent: account={account.id}, chat={chat.id}, "
                f"template={template.id}, msg_id={message_id}"
            )

            return {
                "success": True,
                "mode": "REAL",
                "account_id": account.id,
                "chat_id": chat.id,
                "template_id": template.id,
                "telegram_message_id": message_id,
                "error_message": None,
            }

        except FloodWaitError as e:
            error_msg = f"Flood wait: {e.seconds}s required"
            logger.warning(f"Flood error for chat {chat.id}: {error_msg}")
            raise Exception(error_msg)

        except SlowModeWaitError as e:
            error_msg = f"Slow mode: wait {e.seconds}s"
            logger.warning(f"Slow mode error for chat {chat.id}: {error_msg}")
            raise Exception(error_msg)

        except ChatWriteForbiddenError:
            error_msg = "Chat write forbidden (no permission)"
            logger.warning(f"Write forbidden in chat {chat.id}")
            raise Exception(error_msg)

        except UserBannedInChannelError:
            error_msg = "User banned from chat"
            logger.warning(f"Account {account.id} banned from chat {chat.id}")
            raise Exception(error_msg)

        except ChannelPrivateError:
            error_msg = "Chat is private or no access"
            logger.warning(f"Access denied to chat {chat.id}")
            raise Exception(error_msg)

        except PeerIdInvalidError:
            error_msg = "Invalid chat ID/username"
            logger.warning(f"Invalid chat identifier: {chat.username_or_chat_id}")
            raise Exception(error_msg)

        except RPCError as e:
            error_msg = f"Telegram error: {str(e)}"
            logger.error(f"RPC error in chat {chat.id}: {error_msg}")
            raise Exception(error_msg)

    except UnauthorizedError as e:
        error_msg = str(e)
        logger.warning(f"Authorization error for account {account.id}: {error_msg}")
        return {
            "success": False,
            "mode": "REAL",
            "account_id": account.id,
            "chat_id": chat.id,
            "template_id": template.id,
            "telegram_message_id": None,
            "error_message": error_msg,
            "session_expired": True,
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Send error for chat {chat.id}: {error_msg}")
        return {
            "success": False,
            "mode": "REAL",
            "account_id": account.id,
            "chat_id": chat.id,
            "template_id": template.id,
            "telegram_message_id": None,
            "error_message": error_msg,
        }


async def send_message(
    session: Session,
    account: AdvertisingAccount,
    chat: Chat,
    template: Template,
) -> dict:
    """
    Main sending abstraction.

    This function determines whether to simulate or send real.
    IMPORTANT: This function does NOT commit the session. The caller (scheduler)
    is responsible for session lifecycle and commits.

    Returns a result dict with keys: success, mode, account_id, chat_id,
    template_id, telegram_message_id, error_message, session_expired (optional).
    """
    # Re-fetch entities to ensure fresh state
    account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account.id).first()
    chat = session.query(Chat).filter(Chat.id == chat.id).first()
    template = session.query(Template).filter(Template.id == template.id).first() if template else None

    if not account or not chat:
        logger.error(f"Account or chat not found during send (account_id={account.id if account else 'None'}, chat_id={chat.id if chat else 'None'})")
        return {
            "success": False,
            "mode": "SKIPPED",
            "account_id": account.id if account else -1,
            "chat_id": chat.id if chat else -1,
            "template_id": template.id if template else None,
            "error_message": "Account or chat not found",
        }

    # Check if we can send (re-check to catch any race conditions)
    can_send, reason = await can_send_chat(account, chat, template)
    if not can_send:
        logger.debug(f"Skipping chat {chat.id}: {reason}")
        return {
            "success": False,
            "mode": "SKIPPED",
            "account_id": account.id,
            "chat_id": chat.id,
            "template_id": template.id if template else None,
            "error_message": reason,
        }

    # Choose simulation or real sending
    if DRY_RUN:
        result = await simulate_send(account, chat, template)
    else:
        result = await real_send(account, chat, template)

    # Always create log
    log_entry = SendLog(
        account_id=result["account_id"],
        chat_id=result["chat_id"],
        template_id=result["template_id"],
        status="success" if result["success"] else "error",
        mode=result.get("mode", "SIMULATION"),
        error_message=result.get("error_message"),
        telegram_message_id=result.get("telegram_message_id"),
    )
    session.add(log_entry)

    # Update chat and account state
    if result["success"]:
        chat.last_sent_at = datetime.utcnow()
        chat.last_error = None
        if chat.status == "error":
            chat.status = "active"
    else:
        if result.get("session_expired"):
            account.session_connected = False
            account.last_error = result.get("error_message")

        chat.last_error = result.get("error_message")

        # Set chat to error status only for certain types
        if "permission" in result.get("error_message", "").lower():
            chat.status = "error"

    logger.info(
        f"Send complete: account={account.id}, chat={chat.id}, "
        f"success={result['success']}, mode={result.get('mode', 'SIMULATION')}"
    )

    return result


def format_send_result(result: dict) -> str:
    """Format send result for display."""
    if result["mode"] == "SKIPPED":
        return f"⏭️ Skipped: {result.get('error_message', 'Unknown reason')}"

    if result["success"]:
        mode_text = "📤 REAL" if result["mode"] == "REAL" else "📋 SIMULATION"
        return f"{mode_text} - Sent successfully"

    mode_text = "❌ REAL" if result["mode"] == "REAL" else "❌ SIMULATION"
    return f"{mode_text} - Error: {result.get('error_message', 'Unknown')}"
