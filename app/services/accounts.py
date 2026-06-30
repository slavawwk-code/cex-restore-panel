import logging
from sqlalchemy.orm import Session
from app.database.models import AdvertisingAccount, Chat

logger = logging.getLogger(__name__)


def create_account(
    session: Session,
    display_name: str,
    phone_number: str,
    telethon_session: str,
) -> AdvertisingAccount:
    """Create a new advertising account."""
    account = AdvertisingAccount(
        display_name=display_name,
        phone_number=phone_number,
        telethon_session=telethon_session,
        status="warming",
    )
    session.add(account)
    session.commit()
    logger.info("Created account: %s", display_name)
    return account


def list_accounts(session: Session) -> list[AdvertisingAccount]:
    """Get all advertising accounts."""
    return session.query(AdvertisingAccount).all()


def get_account(session: Session, account_id: int) -> AdvertisingAccount | None:
    """Get a specific account by ID."""
    return session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()


def get_account_by_phone(session: Session, phone_number: str) -> AdvertisingAccount | None:
    """Check if account with phone number already exists."""
    return session.query(AdvertisingAccount).filter(AdvertisingAccount.phone_number == phone_number).first()


def update_account_status(session: Session, account_id: int, status: str) -> bool:
    """Update account status. Returns True if successful."""
    account = get_account(session, account_id)
    if not account:
        logger.warning(f"Account {account_id} not found")
        return False

    valid_statuses = ["active", "paused", "warming", "disabled"]
    if status not in valid_statuses:
        logger.warning(f"Invalid status: {status}")
        return False

    account.status = status
    account.last_error = None
    session.commit()
    logger.info(f"Account {account_id} status changed to {status}")
    return True


def count_account_chats(session: Session, account_id: int) -> int:
    """Count number of chats assigned to an account."""
    return session.query(Chat).filter(Chat.advertising_account_id == account_id).count()


def count_active_chats(session: Session, account_id: int) -> int:
    """Count active chats for an account."""
    return (
        session.query(Chat)
        .filter(Chat.advertising_account_id == account_id, Chat.status == "active")
        .count()
    )


def get_account_info(session: Session, account_id: int) -> dict | None:
    """Get detailed account information."""
    account = get_account(session, account_id)
    if not account:
        return None

    total_chats = count_account_chats(session, account_id)
    active_chats = count_active_chats(session, account_id)

    return {
        "id": account.id,
        "display_name": account.display_name,
        "phone_number": account.phone_number,
        "status": account.status,
        "total_chats": total_chats,
        "active_chats": active_chats,
        "last_error": account.last_error,
        "created_at": account.created_at,
    }


def disable_account(session: Session, account_id: int) -> bool:
    """Soft disable an account."""
    return update_account_status(session, account_id, "disabled")
