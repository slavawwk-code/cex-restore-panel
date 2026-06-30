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


@router.callback_query(F.data == "validator_menu")
async def callback_validator_menu(query: CallbackQuery):
    """Show validator menu."""
    await query.message.edit_text(
        "✅ Проверка и симуляция\n\n"
        "Проверьте конфигурацию и будущие отправки до включения рабочего режима.",
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

        text = "🔍 Проверка кампании\n\n"
        text += f"Проверено аккаунтов: {summary['accounts_checked']}\n"
        text += f"Проверено чатов: {summary['chats_checked']}\n"
        text += f"Проверено шаблонов: {summary['templates_checked']}\n"
        text += f"Найдено проблем: {summary['total_issues']}\n\n"

        if summary["is_valid"]:
            text += "✅ Кампания готова к работе\n\n"
        else:
            text += "❌ Обнаружены проблемы:\n\n"

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
            text = "🧪 Симуляция следующей отправки\n\n"
            text += f"❌ {result['reason']}\n\n"
            text += "Подходящих чатов не найдено."
        else:
            text = "🧪 Симуляция следующей отправки\n\n"

            if result["would_send"]:
                text += "✅ БУДЕТ ОТПРАВЛЕНО СЕЙЧАС\n\n"
            else:
                text += "⏱️ ЗАПЛАНИРОВАНО НА ПОЗЖЕ\n\n"

            text += f"📱 Аккаунт: {result['account_name']}\n"
            text += f"💬 Чат: {result['chat_title']}\n"
            text += f"📝 Шаблон: {result['template_name']}\n"
            text += f"⏱️ Интервал: {result['cooldown']} мин.\n"

            if result["time_remaining"].total_seconds() > 0:
                mins = int(result["time_remaining"].total_seconds() / 60)
                text += f"⏲️ Через: {mins} мин.\n"
            else:
                text += "⏲️ Сейчас\n"

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

        text = "💪 Проверка системы\n\n"

        text += "📱 Рекламные аккаунты\n"
        text += f"✅ Подключено: {connected}\n"
        if disconnected > 0:
            text += f"❌ Не подключено: {disconnected}\n"
        text += "\n"

        text += "📝 Конфигурация\n"
        text += "✅ База данных доступна\n"
        text += "✅ Данные загружены\n\n"

        # Overall health
        total_accounts = len(accounts)
        if total_accounts > 0:
            health_percent = (connected / total_accounts) * 100
            text += f"📊 Общая готовность: {int(health_percent)}%\n"

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
            text = "📅 Предпросмотр расписания\n\n"
            text += "Запланированных отправок нет.\n"
        else:
            text = "📅 Ближайшие 20 отправок\n\n"
            text += format_next_sends_list(sends, "Запланированные отправки")
            text += f"\n⏱️ Оценка длительности кампании: {duration}\n"

        await query.message.edit_text(text, reply_markup=get_validator_back_keyboard())

    finally:
        session.close()
    await query.answer()
