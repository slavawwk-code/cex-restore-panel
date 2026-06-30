import logging
from sqlalchemy.orm import Session
from app.database.models import Chat, AdvertisingAccount, Template

logger = logging.getLogger(__name__)


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
