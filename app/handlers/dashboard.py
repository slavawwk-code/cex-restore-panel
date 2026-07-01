import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.keyboards.dashboard import get_dashboard_menu, get_dashboard_view_keyboard
from app.keyboards.campaigns import get_campaigns_list_keyboard
from app.database import get_session
from app.services.account_health import calculate_account_health, system_health_score
from app.services.dashboard import get_dashboard_stats
from app.database.models import AdvertisingAccount
from app.ui.cards import format_dashboard_card
from app.scheduler import SchedulerService
from app.services.campaigns import list_campaigns

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
    session = get_session()
    try:
        campaigns = list_campaigns(session, include_inactive=True)
        scheduler_running = scheduler_service.running if scheduler_service else False
        if campaigns:
            text = "<b>Кампании</b>\n\nВыберите кампанию для просмотра или редактирования."
            reply_markup = get_campaigns_list_keyboard(campaigns, scheduler_running)
        else:
            text = (
                "<b>Кампании</b>\n\n"
                "Кампании пока не созданы.\n\n"
                "Управление системой доступно ниже."
            )
            reply_markup = get_campaigns_list_keyboard([], scheduler_running)
        await query.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "dashboard_view")
async def callback_dashboard_view(query: CallbackQuery):
    """View the dashboard."""
    session = get_session()
    try:
        stats = get_dashboard_stats(session)
        scheduler_running = scheduler_service.running if scheduler_service else False
        accounts = session.query(AdvertisingAccount).all()
        account_health = [
            (
                account,
                calculate_account_health(session, account, scheduler_running),
            )
            for account in accounts
        ]
        overall = system_health_score([health for _, health in account_health])

        await query.message.edit_text(
            format_dashboard_card(stats, account_health, overall),
            reply_markup=get_dashboard_view_keyboard(accounts),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "dashboard_refresh")
async def callback_dashboard_refresh(query: CallbackQuery):
    """Refresh the dashboard."""
    await callback_dashboard_view(query)
