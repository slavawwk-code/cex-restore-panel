import logging
import os
from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.keyboards.dashboard import get_dashboard_menu, get_dashboard_view_keyboard
from app.keyboards.logs import get_logs_menu
from app.database import get_session
from app.services.dashboard import get_dashboard_stats, get_next_scheduled_sends, format_next_sends_list
from app.scheduler import SchedulerService

router = Router()
logger = logging.getLogger(__name__)

# Global scheduler reference (will be set from main.py)
scheduler_service = None


def set_scheduler(scheduler: SchedulerService):
    """Set the scheduler service reference."""
    global scheduler_service
    scheduler_service = scheduler


@router.callback_query(F.data == "campaigns_menu")
async def callback_campaigns_menu(query: CallbackQuery):
    """Handle campaigns/dashboard menu callback."""
    await query.message.edit_text(
        "📊 Campaigns Dashboard\n\nView system overview and logs.",
        reply_markup=get_dashboard_menu(),
    )
    await query.answer()


@router.callback_query(F.data == "dashboard_view")
async def callback_dashboard_view(query: CallbackQuery):
    """View the dashboard."""
    session = get_session()
    try:
        stats = get_dashboard_stats(session)
        dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
        scheduler_running = scheduler_service.running if scheduler_service else False

        text = "📊 Campaign Dashboard\n\n"

        # Accounts section
        text += "📱 Advertising Accounts\n"
        text += f"  Total: {stats['accounts']['total']}\n"
        text += f"  🟢 Active: {stats['accounts']['active']}\n"
        text += f"  ⏸️ Paused: {stats['accounts']['paused']}\n"
        text += f"  🔥 Warming: {stats['accounts']['warming']}\n"
        text += f"  🚫 Disabled: {stats['accounts']['disabled']}\n\n"

        # Chats section
        text += "💬 Configured Chats\n"
        text += f"  Total: {stats['chats']['total']}\n"
        text += f"  🟢 Active: {stats['chats']['active']}\n"
        text += f"  ⏸️ Paused: {stats['chats']['paused']}\n"
        text += f"  ⚠️ Error: {stats['chats']['error']}\n"
        text += f"  🚫 Disabled: {stats['chats']['disabled']}\n\n"

        # Templates section
        text += "📝 Message Templates\n"
        text += f"  Total: {stats['templates']['total']}\n"
        text += f"  ✅ Active: {stats['templates']['active']}\n"
        text += f"  🚫 Disabled: {stats['templates']['disabled']}\n\n"

        # Scheduler section
        text += "⚙️ Scheduler Status\n"
        scheduler_status = "✅ RUNNING" if scheduler_running else "⏹️ STOPPED"
        dry_run_status = "ON (Simulated)" if dry_run else "OFF (Real Sends)"
        text += f"  {scheduler_status}\n"
        text += f"  DRY_RUN: {dry_run_status}\n\n"

        # Activity section
        text += "📈 Activity Today\n"
        text += f"  ✅ Sends: {stats['sends']['today']}\n"
        text += f"  ❌ Errors: {stats['sends']['errors_today']}\n"

        if stats["sends"]["last_success"]:
            last_success_time = stats["sends"]["last_success"].sent_at.strftime("%H:%M:%S")
            text += f"  Last success: {last_success_time}\n"

        if stats["sends"]["last_error"]:
            last_error_time = stats["sends"]["last_error"].sent_at.strftime("%H:%M:%S")
            text += f"  Last error: {last_error_time}\n"

        # Next scheduled sends
        text += "\n⏰ Next Scheduled Sends\n"
        next_sends = get_next_scheduled_sends(session, limit=10)
        if next_sends:
            text += format_next_sends_list(next_sends)
        else:
            text += "(No active chats scheduled)\n"

        await query.message.edit_text(
            text,
            reply_markup=get_dashboard_view_keyboard(),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "dashboard_refresh")
async def callback_dashboard_refresh(query: CallbackQuery):
    """Refresh the dashboard."""
    await callback_dashboard_view(query)
