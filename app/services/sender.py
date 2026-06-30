import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import AdvertisingAccount, Chat, Template, SendLog
from app.config import load_settings
from app.services.account_orchestrator import account_orchestrator
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

DRY_RUN = load_settings(require_secrets=False).dry_run
# Backward-compatible alias. The orchestrator owns the actual client manager.
telethon_manager = account_orchestrator.client_manager


async def can_send_chat(account: AdvertisingAccount, chat: Chat, template: Template) -> tuple[bool, str]:
    """
    Check if a chat is eligible for sending.
    Returns (can_send, reason).
    """
    # Check account
    if not account:
        return False, "Аккаунт не найден"
    if account.status != "active":
        status_label = {
            "paused": "на паузе",
            "warming": "на прогреве",
            "disabled": "отключён",
        }.get(account.status, "неактивен")
        return False, f"Аккаунт {status_label}"
    if not account.session_connected:
        return False, "Сессия аккаунта не подключена"

    # Check chat
    if not chat.is_active:
        return False, "Чат отключён"
    if chat.status == "paused":
        return False, "Чат приостановлен"
    if chat.status == "error":
        return False, "Чат находится в состоянии ошибки"

    # Check template
    if not template:
        return False, "Шаблон не назначен"
    if not template.is_active:
        return False, "Шаблон отключён"

    # Check cooldown
    if chat.cooldown_minutes < 1 or chat.cooldown_minutes > 1440:
        return False, "Указан неверный интервал отправки"

    # Check if cooldown expired
    if chat.last_sent_at:
        elapsed = (datetime.utcnow() - chat.last_sent_at).total_seconds() / 60
        if elapsed < chat.cooldown_minutes:
            return False, f"Интервал ещё не истёк: {int(chat.cooldown_minutes - elapsed)} мин."

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
            raise UnauthorizedError("Сессия аккаунта не подключена")

        try:
            async def send_through_client(client, _fresh_account):
                if not client.is_connected():
                    await client.connect()
                if not await client.is_user_authorized():
                    raise UnauthorizedError("Клиент Telegram не авторизован")
                return await client.send_message(
                    chat.username_or_chat_id, template.text
                )

            message = await account_orchestrator.run_client_operation(
                account.id,
                "send_message",
                send_through_client,
            )
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
            error_msg = f"Лимит Telegram: повторите через {e.seconds} сек."
            logger.warning(f"Flood error for chat {chat.id}: {error_msg}")
            raise Exception(error_msg)

        except SlowModeWaitError as e:
            error_msg = f"Медленный режим чата: подождите {e.seconds} сек."
            logger.warning(f"Slow mode error for chat {chat.id}: {error_msg}")
            raise Exception(error_msg)

        except ChatWriteForbiddenError:
            error_msg = "Нет разрешения на отправку сообщений в чат"
            logger.warning(f"Write forbidden in chat {chat.id}")
            raise Exception(error_msg)

        except UserBannedInChannelError:
            error_msg = "Аккаунт заблокирован в чате"
            logger.warning(f"Account {account.id} banned from chat {chat.id}")
            raise Exception(error_msg)

        except ChannelPrivateError:
            error_msg = "Чат закрыт или недоступен аккаунту"
            logger.warning(f"Access denied to chat {chat.id}")
            raise Exception(error_msg)

        except PeerIdInvalidError:
            error_msg = "Неверный ID или username чата"
            logger.warning(f"Invalid chat identifier: {chat.username_or_chat_id}")
            raise Exception(error_msg)

        except RPCError as e:
            error_msg = f"Ошибка Telegram: {type(e).__name__}"
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
            "error_message": "Аккаунт или чат не найден",
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
        return f"⏭️ Пропущено: {result.get('error_message', 'причина неизвестна')}"

    if result["success"]:
        mode_text = "📤 РЕАЛЬНАЯ" if result["mode"] == "REAL" else "📋 СИМУЛЯЦИЯ"
        return f"{mode_text} — успешно"

    mode_text = "❌ РЕАЛЬНАЯ" if result["mode"] == "REAL" else "❌ СИМУЛЯЦИЯ"
    return f"{mode_text} — ошибка: {result.get('error_message', 'неизвестно')}"
