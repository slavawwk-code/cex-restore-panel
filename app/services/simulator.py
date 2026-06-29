import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database.models import Chat, SendLog, AdvertisingAccount

logger = logging.getLogger(__name__)


async def simulate_send(account: AdvertisingAccount, chat: Chat, template) -> dict:
    """
    Simulate sending a message.

    This is the abstraction point - in production, this would be replaced with real_send().
    Everything else should remain unchanged.
    """
    return {
        "success": True,
        "account_name": account.display_name,
        "chat_title": chat.title,
        "template_name": template.name if template else "None",
        "message": f"[SIMULATION] Would send '{template.name}' to {chat.title}",
    }


def simulate_next_send(session: Session) -> dict:
    """Simulate next send based on scheduler logic."""
    now = datetime.utcnow()

    # Get all active chats with active accounts and templates
    chats = (
        session.query(Chat)
        .filter(
            Chat.is_active == True,
            Chat.status == "active",
        )
        .all()
    )

    next_candidate = None
    next_time = None

    for chat in chats:
        # Check if account and template are active
        if not chat.account or chat.account.status != "active":
            continue
        if not chat.template or not chat.template.is_active:
            continue

        # Calculate next send time
        if chat.last_sent_at:
            send_time = chat.last_sent_at + timedelta(minutes=chat.cooldown_minutes)
        else:
            send_time = now  # Never sent, available now

        # Track earliest
        if next_time is None or send_time < next_time:
            next_time = send_time
            next_candidate = {
                "chat": chat,
                "time": send_time,
                "would_send": send_time <= now,
            }

    if not next_candidate:
        return {
            "found": False,
            "reason": "No eligible chats",
        }

    chat = next_candidate["chat"]
    time_diff = next_candidate["time"] - now

    return {
        "found": True,
        "would_send": next_candidate["would_send"],
        "account_name": chat.account.display_name,
        "chat_title": chat.title,
        "template_name": chat.template.name if chat.template else "None",
        "next_time": next_candidate["time"],
        "time_remaining": time_diff,
        "cooldown": chat.cooldown_minutes,
        "last_sent": chat.last_sent_at,
    }


def simulate_campaign(session: Session) -> dict:
    """Simulate the entire campaign - check every chat."""
    now = datetime.utcnow()

    # Get all active chats
    chats = (
        session.query(Chat)
        .filter(Chat.is_active == True)
        .order_by(Chat.title)
        .all()
    )

    results = {
        "would_send": [],
        "paused": [],
        "errors": [],
        "total": len(chats),
    }

    for chat in chats:
        # Determine status
        if chat.status == "paused":
            results["paused"].append({
                "chat_title": chat.title,
                "account_name": chat.account.display_name if chat.account else "Unknown",
                "reason": "Chat paused",
            })
            continue

        if chat.status == "error":
            results["errors"].append({
                "chat_title": chat.title,
                "account_name": chat.account.display_name if chat.account else "Unknown",
                "reason": "Chat in error state",
            })
            continue

        # Check configuration
        if not chat.account:
            results["errors"].append({
                "chat_title": chat.title,
                "reason": "Account missing",
            })
            continue

        if chat.account.status == "disabled":
            results["errors"].append({
                "chat_title": chat.title,
                "account_name": chat.account.display_name,
                "reason": "Account disabled",
            })
            continue

        if not chat.template:
            results["errors"].append({
                "chat_title": chat.title,
                "account_name": chat.account.display_name,
                "reason": "No template assigned",
            })
            continue

        if not chat.template.is_active:
            results["errors"].append({
                "chat_title": chat.title,
                "account_name": chat.account.display_name,
                "reason": "Template disabled",
            })
            continue

        if not chat.account.session_connected:
            results["errors"].append({
                "chat_title": chat.title,
                "account_name": chat.account.display_name,
                "reason": "Session not connected",
            })
            continue

        # Would send
        results["would_send"].append({
            "chat_title": chat.title,
            "account_name": chat.account.display_name,
            "template_name": chat.template.name,
        })

    results["would_send_count"] = len(results["would_send"])
    results["paused_count"] = len(results["paused"])
    results["error_count"] = len(results["errors"])

    return results


def preview_schedule(session: Session, limit: int = 20) -> list:
    """Preview the next scheduled sends."""
    now = datetime.utcnow()

    # Get all active chats with valid config
    chats = (
        session.query(Chat)
        .filter(
            Chat.is_active == True,
            Chat.status == "active",
        )
        .all()
    )

    scheduled = []

    for chat in chats:
        # Check validity
        if not chat.account or chat.account.status != "active":
            continue
        if not chat.template or not chat.template.is_active:
            continue
        if not chat.account.session_connected:
            continue

        # Calculate next send
        if chat.last_sent_at:
            next_time = chat.last_sent_at + timedelta(minutes=chat.cooldown_minutes)
        else:
            next_time = now

        scheduled.append({
            "time": next_time,
            "account_name": chat.account.display_name,
            "chat_title": chat.title,
            "template_name": chat.template.name,
            "status": "READY",
        })

    # Sort by time
    scheduled.sort(key=lambda x: x["time"])

    return scheduled[:limit]


def estimate_campaign_duration(sends: list) -> str:
    """Estimate how long campaign would take."""
    if not sends:
        return "No sends scheduled"

    first_time = sends[0]["time"]
    last_time = sends[-1]["time"] if len(sends) > 1 else first_time

    duration = last_time - first_time
    hours = duration.total_seconds() / 3600

    if hours < 1:
        minutes = int(duration.total_seconds() / 60)
        return f"{minutes} minutes"
    elif hours < 24:
        return f"{int(hours)} hours"
    else:
        days = hours / 24
        return f"{days:.1f} days"


def format_campaign_simulation(result: dict) -> str:
    """Format campaign simulation results for display."""
    text = "🧪 Campaign Simulation\n\n"

    text += f"📊 Summary\n"
    text += f"Total chats checked: {result['total']}\n"
    text += f"✅ Would send: {result['would_send_count']}\n"
    text += f"⏸️ Paused: {result['paused_count']}\n"
    text += f"❌ Errors: {result['error_count']}\n\n"

    if result["would_send"]:
        text += f"✅ Ready to Send\n"
        for send in result["would_send"][:5]:
            text += f"  • {send['chat_title']} ({send['account_name']})\n"
        if len(result["would_send"]) > 5:
            text += f"  ... and {len(result['would_send']) - 5} more\n"
        text += "\n"

    if result["paused"]:
        text += f"⏸️ Paused Chats\n"
        for item in result["paused"][:3]:
            text += f"  • {item['chat_title']}\n"
        if len(result["paused"]) > 3:
            text += f"  ... and {len(result['paused']) - 3} more\n"
        text += "\n"

    if result["errors"]:
        text += f"❌ Errors\n"
        for item in result["errors"][:5]:
            text += f"  • {item['chat_title']}: {item['reason']}\n"
        if len(result["errors"]) > 5:
            text += f"  ... and {len(result['errors']) - 5} more\n"

    return text
