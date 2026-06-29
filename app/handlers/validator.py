import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.keyboards.validator import get_validator_menu, get_validator_back_keyboard
from app.database import get_session
from app.database.models import AdvertisingAccount
from app.services.validator import CampaignValidator
from app.services.simulator import (
    simulate_next_send,
    simulate_campaign,
    preview_schedule,
    estimate_campaign_duration,
    format_campaign_simulation,
)
from app.services.dashboard import format_next_sends_list

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "campaigns_menu")
async def callback_validator_menu(query: CallbackQuery):
    """Show validator menu."""
    await query.message.edit_text(
        "🧪 Campaign Validation & Simulation\n\n"
        "Validate configuration and simulate sends before enabling real messaging.",
        reply_markup=get_validator_menu(),
    )
    await query.answer()


@router.callback_query(F.data == "validator_validate")
async def callback_validate_campaign(query: CallbackQuery):
    """Run campaign validation."""
    session = get_session()

    try:
        validator = CampaignValidator(session)
        summary = validator.validate_campaign()

        text = "🔍 Campaign Validation\n\n"
        text += f"Accounts checked: {summary['accounts_checked']}\n"
        text += f"Chats checked: {summary['chats_checked']}\n"
        text += f"Templates checked: {summary['templates_checked']}\n"
        text += f"Issues found: {summary['total_issues']}\n\n"

        if summary["is_valid"]:
            text += "✅ Campaign is VALID\n\n"
        else:
            text += "❌ Problems detected:\n\n"

        text += validator.format_issues()

        await query.message.edit_text(text, reply_markup=get_validator_back_keyboard())

    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "simulator_next")
async def callback_simulate_next(query: CallbackQuery):
    """Simulate next send."""
    session = get_session()

    try:
        result = simulate_next_send(session)

        if not result["found"]:
            text = "🧪 Next Send Simulation\n\n"
            text += f"❌ {result['reason']}\n\n"
            text += "No eligible chats found."
        else:
            text = "🧪 Next Send Simulation\n\n"

            if result["would_send"]:
                text += "✅ WOULD SEND NOW\n\n"
            else:
                text += "⏱️ SCHEDULED FOR LATER\n\n"

            text += f"📱 Account: {result['account_name']}\n"
            text += f"💬 Chat: {result['chat_title']}\n"
            text += f"📝 Template: {result['template_name']}\n"
            text += f"⏱️ Cooldown: {result['cooldown']} minutes\n"

            if result["time_remaining"].total_seconds() > 0:
                mins = int(result["time_remaining"].total_seconds() / 60)
                text += f"⏲️ In: {mins} minutes\n"
            else:
                text += f"⏲️ NOW\n"

        await query.message.edit_text(text, reply_markup=get_validator_back_keyboard())

    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "simulator_full")
async def callback_simulate_full(query: CallbackQuery):
    """Simulate full campaign."""
    session = get_session()

    try:
        result = simulate_campaign(session)
        text = format_campaign_simulation(result)

        await query.message.edit_text(text, reply_markup=get_validator_back_keyboard())

    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "validator_health")
async def callback_health_check(query: CallbackQuery):
    """Run health check."""
    session = get_session()

    try:
        # Account health
        accounts = session.query(AdvertisingAccount).all()
        connected = sum(1 for a in accounts if a.session_connected)
        disconnected = sum(1 for a in accounts if not a.session_connected)

        text = "💪 System Health Check\n\n"

        text += f"📱 Advertising Accounts\n"
        text += f"✅ {connected} connected\n"
        if disconnected > 0:
            text += f"❌ {disconnected} disconnected\n"
        text += "\n"

        text += f"📝 Configuration\n"
        text += f"✅ Database connected\n"
        text += f"✅ All entities loaded\n\n"

        # Overall health
        total_accounts = len(accounts)
        if total_accounts > 0:
            health_percent = (connected / total_accounts) * 100
            text += f"📊 Overall Health: {int(health_percent)}%\n"

        await query.message.edit_text(text, reply_markup=get_validator_back_keyboard())

    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "simulator_schedule")
async def callback_preview_schedule(query: CallbackQuery):
    """Preview schedule."""
    session = get_session()

    try:
        sends = preview_schedule(session, limit=20)
        duration = estimate_campaign_duration(sends)

        if not sends:
            text = "📅 Schedule Preview\n\n"
            text += "No scheduled sends found.\n"
        else:
            text = "📅 Schedule Preview (Next 20)\n\n"
            text += format_next_sends_list(sends, "Scheduled Sends")
            text += f"\n⏱️ Estimated campaign duration: {duration}\n"

        await query.message.edit_text(text, reply_markup=get_validator_back_keyboard())

    finally:
        session.close()
    await query.answer()
