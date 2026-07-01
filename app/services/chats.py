import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.database.models import Chat, AdvertisingAccount, Template
from app.services.account_orchestrator import account_orchestrator
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerIdInvalidError,
    RPCError,
    UnauthorizedError,
    UserBannedInChannelError,
    UserPrivacyRestrictedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Channel, Chat as TelegramChat, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatAccessCheck:
    success: bool
    title: str | None = None
    entity_id: int | None = None
    entity_type: str = "unknown"
    access_ok: bool = False
    can_write: bool | None = None
    reason: str | None = None

    def format_diagnostics(self) -> str:
        write_status = (
            "OK"
            if self.can_write is True
            else "нет"
            if self.can_write is False
            else "не проверено до отправки"
        )
        lines = []
        if self.title:
            lines.append(f"Чат найден: {self.title}")
        if self.access_ok:
            lines.append("Аккаунт имеет доступ")
        lines.append(f"Права на отправку: {write_status}")
        if self.reason:
            lines.append(f"Причина: {self.reason}")
        return "\n".join(lines)


def create_chat(
    session: Session,
    advertising_account_id: int,
    template_id: int,
    title: str,
    username_or_chat_id: str,
    cooldown_minutes: int,
) -> Chat:
    """Create a new chat configuration."""
    chat = Chat(
        advertising_account_id=advertising_account_id,
        template_id=template_id,
        title=title.strip(),
        username_or_chat_id=username_or_chat_id.strip(),
        cooldown_minutes=cooldown_minutes,
        status="active",
        is_active=True,
    )
    session.add(chat)
    session.commit()
    logger.info(f"Created chat: {title} (account_id={advertising_account_id})")
    return chat


async def inspect_chat_access(
    session: Session,
    account_id: int,
    username_or_chat_id: str,
) -> ChatAccessCheck:
    """Resolve a Telegram entity and report operator-friendly send diagnostics."""
    account = session.get(AdvertisingAccount, account_id)
    if not account:
        return ChatAccessCheck(False, reason="Аккаунт не найден")
    if account.status != "active":
        return ChatAccessCheck(False, reason="Аккаунт не активен")
    if not account.session_connected:
        return ChatAccessCheck(False, reason="Сессия аккаунта не подключена")

    identifier = username_or_chat_id.strip()
    if not identifier:
        return ChatAccessCheck(False, reason="Не указан username или ID чата")

    try:
        async def inspect_with_client(client, _fresh_account):
            if not client.is_connected():
                await client.connect()
            if not await client.is_user_authorized():
                raise UnauthorizedError("Клиент Telegram не авторизован")
            entity = await client.get_entity(identifier)
            title = _entity_title(entity)
            can_write, reason = _entity_send_permission(entity)
            return ChatAccessCheck(
                success=True,
                title=(title[:100] if title else None),
                entity_id=getattr(entity, "id", None),
                entity_type=type(entity).__name__,
                access_ok=True,
                can_write=can_write,
                reason=reason,
            )

        return await account_orchestrator.run_client_operation(
            account_id,
            "inspect_chat_access",
            inspect_with_client,
        )
    except Exception as error:
        logger.exception(
            "Chat access inspection failed account_id=%s identifier=%s",
            account_id,
            identifier,
        )
        return ChatAccessCheck(False, reason=format_chat_access_error(error))


def format_chat_access_error(error: Exception) -> str:
    """Translate Telethon/chat access failures for the operator."""
    text = str(error)
    if isinstance(error, UnauthorizedError) or "не авториз" in text.lower():
        return "Сессия аккаунта не подключена или не авторизована"
    if isinstance(error, (UsernameInvalidError, PeerIdInvalidError)):
        return "Неверный username или chat ID"
    if isinstance(error, UsernameNotOccupiedError):
        return "Username не найден в Telegram"
    if isinstance(error, ChannelPrivateError):
        return "Чат закрыт или аккаунт не состоит в группе/канале"
    if isinstance(error, ChatWriteForbiddenError):
        return "У аккаунта нет права писать в этот чат"
    if isinstance(error, UserBannedInChannelError):
        return "Аккаунт заблокирован в этом чате"
    if isinstance(error, UserPrivacyRestrictedError):
        return "Telegram privacy restriction: нельзя написать пользователю первым"
    if isinstance(error, ChatAdminRequiredError):
        return "Для доступа или отправки нужны права администратора"
    if isinstance(error, FloodWaitError):
        return f"Telegram ограничил запросы. Повторите через {error.seconds} сек."
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return "Прокси или сеть недоступны"
    if isinstance(error, RPCError):
        return f"Ошибка Telegram: {type(error).__name__}"
    return f"{type(error).__name__}: {text or 'неизвестная ошибка'}"


def _entity_title(entity) -> str:
    if isinstance(entity, User):
        name = " ".join(
            item
            for item in (entity.first_name, entity.last_name)
            if item
        ).strip()
        return name or entity.username or f"User {entity.id}"
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or f"Chat {getattr(entity, 'id', '')}".strip()
    )


def _entity_send_permission(entity) -> tuple[bool | None, str | None]:
    if isinstance(entity, User):
        return None, "Для личных сообщений Telegram может запретить писать первым"
    if isinstance(entity, (Channel, TelegramChat)):
        rights = getattr(entity, "default_banned_rights", None)
        if rights and getattr(rights, "send_messages", False):
            return False, "В чате запрещена отправка сообщений"
        if getattr(entity, "broadcast", False) and not getattr(entity, "megagroup", False):
            return False, "Это канал; для публикации нужны права администратора"
        return True, None
    return None, "Тип чата не позволяет заранее проверить права отправки"


def list_chats(session: Session, account_id: int = None, include_inactive: bool = False) -> list[Chat]:
    """Get all chats, optionally filtered by account and active status."""
    query = session.query(Chat)

    if not include_inactive:
        query = query.filter(Chat.is_active.is_(True))

    if account_id:
        query = query.filter(Chat.advertising_account_id == account_id)

    return query.all()


def get_chat(session: Session, chat_id: int) -> Chat | None:
    """Get a specific chat by ID."""
    return session.query(Chat).filter(Chat.id == chat_id).first()


def get_chat_info(session: Session, chat_id: int) -> dict | None:
    """Get detailed chat information."""
    chat = get_chat(session, chat_id)
    if not chat:
        return None

    account = chat.account
    template = chat.template

    return {
        "id": chat.id,
        "title": chat.title,
        "username_or_chat_id": chat.username_or_chat_id,
        "account_id": chat.advertising_account_id,
        "account_name": account.display_name if account else "неизвестно",
        "template_id": chat.assigned_template_id,
        "template_name": template.name if template else "не назначен",
        "cooldown_minutes": chat.cooldown_minutes,
        "status": chat.status,
        "is_active": chat.is_active,
        "last_sent_at": chat.last_sent_at,
        "last_error": chat.last_error,
        "created_at": chat.created_at,
    }


def update_chat_account(session: Session, chat_id: int, new_account_id: int) -> bool:
    """Change the account assigned to a chat."""
    chat = get_chat(session, chat_id)
    if not chat:
        logger.warning(f"Chat {chat_id} not found")
        return False

    account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == new_account_id).first()
    if not account:
        logger.warning(f"Account {new_account_id} not found")
        return False

    chat.advertising_account_id = new_account_id
    session.commit()
    logger.info(f"Chat {chat_id} account changed to {account.display_name}")
    return True


def update_chat_template(session: Session, chat_id: int, new_template_id: int) -> bool:
    """Change the template assigned to a chat."""
    chat = get_chat(session, chat_id)
    if not chat:
        logger.warning(f"Chat {chat_id} not found")
        return False

    template = session.query(Template).filter(Template.id == new_template_id).first()
    if not template:
        logger.warning(f"Template {new_template_id} not found")
        return False

    chat.assigned_template_id = new_template_id
    session.commit()
    logger.info(f"Chat {chat_id} template changed to {template.name}")
    return True


def update_chat_cooldown(session: Session, chat_id: int, new_cooldown: int) -> bool:
    """Change the cooldown for a chat."""
    chat = get_chat(session, chat_id)
    if not chat:
        logger.warning(f"Chat {chat_id} not found")
        return False

    if new_cooldown < 1 or new_cooldown > 1440:
        logger.warning(f"Invalid cooldown: {new_cooldown}")
        return False

    chat.cooldown_minutes = new_cooldown
    session.commit()
    logger.info(f"Chat {chat_id} cooldown changed to {new_cooldown} minutes")
    return True


def update_chat_status(session: Session, chat_id: int, new_status: str) -> bool:
    """Update chat status."""
    chat = get_chat(session, chat_id)
    if not chat:
        logger.warning(f"Chat {chat_id} not found")
        return False

    valid_statuses = ["active", "paused", "error"]
    if new_status not in valid_statuses:
        logger.warning(f"Invalid status: {new_status}")
        return False

    chat.status = new_status
    if new_status != "error":
        chat.last_error = None
    session.commit()
    logger.info(f"Chat {chat_id} status changed to {new_status}")
    return True


def disable_chat(session: Session, chat_id: int) -> bool:
    """Disable a chat (soft delete)."""
    chat = get_chat(session, chat_id)
    if not chat:
        logger.warning(f"Chat {chat_id} not found")
        return False

    chat.is_active = False
    session.commit()
    logger.info(f"Chat {chat_id} disabled")
    return True


def count_account_chats(session: Session, account_id: int, active_only: bool = True) -> int:
    """Count chats for a specific account."""
    query = session.query(Chat).filter(Chat.advertising_account_id == account_id)
    if active_only:
        query = query.filter(Chat.is_active.is_(True))
    return query.count()


def count_template_chats(session: Session, template_id: int, active_only: bool = True) -> int:
    """Count chats using a specific template."""
    query = session.query(Chat).filter(Chat.assigned_template_id == template_id)
    if active_only:
        query = query.filter(Chat.is_active.is_(True))
    return query.count()


def get_status_emoji(status: str) -> str:
    """Get emoji for chat status."""
    return {
        "active": "🟢",
        "paused": "⏸️",
        "error": "⚠️",
    }.get(status, "❓")
