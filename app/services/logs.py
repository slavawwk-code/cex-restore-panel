import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database.models import SendLog, AdvertisingAccount, Chat, Template

logger = logging.getLogger(__name__)


def list_recent_logs(session: Session, limit: int = 20) -> list[SendLog]:
    """Get recent send logs."""
    return session.query(SendLog).order_by(SendLog.sent_at.desc()).limit(limit).all()


def list_error_logs(session: Session, limit: int = 20) -> list[SendLog]:
    """Get error send logs."""
    return (
        session.query(SendLog)
        .filter(SendLog.status == "error")
        .order_by(SendLog.sent_at.desc())
        .limit(limit)
        .all()
    )


def list_success_logs(session: Session, limit: int = 20) -> list[SendLog]:
    """Get successful send logs."""
    return (
        session.query(SendLog)
        .filter(SendLog.status == "success")
        .order_by(SendLog.sent_at.desc())
        .limit(limit)
        .all()
    )


def list_logs_by_account(session: Session, account_id: int, limit: int = 20) -> list[SendLog]:
    """Get logs for a specific account."""
    return (
        session.query(SendLog)
        .filter(SendLog.account_id == account_id)
        .order_by(SendLog.sent_at.desc())
        .limit(limit)
        .all()
    )


def list_logs_by_chat(session: Session, chat_id: int, limit: int = 20) -> list[SendLog]:
    """Get logs for a specific chat."""
    return (
        session.query(SendLog)
        .filter(SendLog.chat_id == chat_id)
        .order_by(SendLog.sent_at.desc())
        .limit(limit)
        .all()
    )


def count_sends_today(session: Session) -> int:
    """Count successful sends today."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.query(SendLog)
        .filter(SendLog.sent_at >= today, SendLog.status == "success")
        .count()
    )


def count_errors_today(session: Session) -> int:
    """Count errors today."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.query(SendLog)
        .filter(SendLog.sent_at >= today, SendLog.status == "error")
        .count()
    )


def get_last_success_log(session: Session) -> SendLog | None:
    """Get the most recent successful send."""
    return (
        session.query(SendLog)
        .filter(SendLog.status == "success")
        .order_by(SendLog.sent_at.desc())
        .first()
    )


def get_last_error_log(session: Session) -> SendLog | None:
    """Get the most recent error."""
    return (
        session.query(SendLog)
        .filter(SendLog.status == "error")
        .order_by(SendLog.sent_at.desc())
        .first()
    )


def format_log_entry(log: SendLog) -> str:
    """Format a send log for display."""
    emoji = "✅" if log.status == "success" else "❌"
    account_name = log.account.display_name if log.account else "Unknown"
    chat_title = log.chat.title if log.chat else "Unknown"
    template_name = log.template.name if log.template else "None"

    text = f"{emoji} {log.sent_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"📱 {account_name} • 💬 {chat_title} • 📝 {template_name}\n"

    if log.error_message:
        text += f"⚠️ Error: {log.error_message[:80]}\n"

    return text


def format_logs_list(logs: list, title: str = "📋 Logs") -> str:
    """Format a list of logs for display."""
    if not logs:
        return f"{title}\n\nNo logs found yet."

    text = f"{title}\n\n"
    for log in logs:
        text += format_log_entry(log)
        text += "\n"

    return text
