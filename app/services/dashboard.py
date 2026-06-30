import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database.models import AdvertisingAccount, Chat, Template, SendLog

logger = logging.getLogger(__name__)


def get_dashboard_stats(session: Session) -> dict:
    """Get complete dashboard statistics."""
    # Account stats
    all_accounts = session.query(AdvertisingAccount).all()
    active_accounts = [a for a in all_accounts if a.status == "active"]
    paused_accounts = [a for a in all_accounts if a.status == "paused"]
    warming_accounts = [a for a in all_accounts if a.status == "warming"]
    disabled_accounts = [a for a in all_accounts if a.status == "disabled"]

    # Chat stats
    all_chats = session.query(Chat).filter(Chat.is_active.is_(True)).all()
    active_chats = [c for c in all_chats if c.status == "active"]
    paused_chats = [c for c in all_chats if c.status == "paused"]
    error_chats = [c for c in all_chats if c.status == "error"]
    disabled_chats = session.query(Chat).filter(Chat.is_active.is_(False)).count()

    # Template stats
    all_templates = session.query(Template).all()
    active_templates = [t for t in all_templates if t.is_active]
    disabled_templates = [t for t in all_templates if not t.is_active]

    # Send stats
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = session.query(SendLog).filter(SendLog.sent_at >= today).all()
    successful_today = [log for log in today_logs if log.status == "success"]
    errors_today = [log for log in today_logs if log.status == "error"]

    # Last sends
    all_logs = session.query(SendLog).order_by(SendLog.sent_at.desc()).all()
    last_success = None
    last_error = None
    for log in all_logs:
        if log.status == "success" and not last_success:
            last_success = log
        if log.status == "error" and not last_error:
            last_error = log
        if last_success and last_error:
            break

    return {
        "accounts": {
            "total": len(all_accounts),
            "active": len(active_accounts),
            "paused": len(paused_accounts),
            "warming": len(warming_accounts),
            "disabled": len(disabled_accounts),
        },
        "chats": {
            "total": len(all_chats),
            "active": len(active_chats),
            "paused": len(paused_chats),
            "error": len(error_chats),
            "disabled": disabled_chats,
        },
        "templates": {
            "total": len(all_templates),
            "active": len(active_templates),
            "disabled": len(disabled_templates),
        },
        "proxy": {
            "online": sum(
                account.proxy_enabled and account.proxy_status == "working"
                for account in all_accounts
            ),
            "offline": sum(
                account.proxy_enabled and account.proxy_status != "working"
                for account in all_accounts
            ),
        },
        "sends": {
            "today": len(successful_today),
            "errors_today": len(errors_today),
            "last_success": last_success,
            "last_error": last_error,
        },
    }


def get_next_scheduled_sends(session: Session, limit: int = 10) -> list:
    """Get the next scheduled sends based on cooldown expiration."""
    now = datetime.utcnow()

    # Get all active chats with active accounts and templates
    chats = (
        session.query(Chat)
        .filter(
            Chat.is_active.is_(True),
            Chat.status == "active",
        )
        .all()
    )

    scheduled = []

    for chat in chats:
        # Check if account and template are active
        if not chat.account or chat.account.status != "active":
            continue
        if not chat.template or not chat.template.is_active:
            continue

        # Calculate next send time
        if chat.last_sent_at:
            next_send = chat.last_sent_at + timedelta(minutes=chat.cooldown_minutes)
        else:
            # Never sent, available now
            next_send = now

        scheduled.append(
            {
                "chat_id": chat.id,
                "chat_title": chat.title,
                "account_name": chat.account.display_name,
                "template_name": chat.template.name,
                "next_send_time": next_send,
                "is_overdue": next_send <= now,
            }
        )

    # Sort by next send time
    scheduled.sort(key=lambda x: x["next_send_time"])

    # Return top N
    return scheduled[:limit]


def format_next_sends_list(sends: list) -> str:
    """Format next sends for display."""
    if not sends:
        return "Ближайших отправок нет"

    now = datetime.utcnow()
    text = ""

    for i, send in enumerate(sends[:10], 1):
        time_diff = send["next_send_time"] - now
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)

        status = "⏲️" if send["is_overdue"] else "⏰"

        if send["is_overdue"]:
            time_str = "сейчас"
        elif hours == 0:
            time_str = f"через {minutes} мин."
        elif hours < 24:
            time_str = f"через {hours} ч. {minutes} мин."
        else:
            time_str = send["next_send_time"].strftime("%d.%m.%Y %H:%M")

        text += f"{i}. {status} {send['chat_title']}\n"
        text += f"   📱 {send['account_name']} • 📝 {send['template_name']}\n"
        text += f"   ⏱️ {time_str}\n\n"

    return text
