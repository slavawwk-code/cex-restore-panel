import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.database.models import Chat
from app.keyboards.campaigns import (
    get_account_campaign_test_keyboard,
    get_campaign_chats_keyboard,
    get_campaign_destructive_confirmation_keyboard,
    get_campaign_detail_keyboard,
    get_campaign_edit_keyboard,
    get_campaign_first_send_keyboard,
    get_campaign_schedule_keyboard,
    get_campaign_template_keyboard,
)
from app.services.campaigns import (
    format_campaign_card,
    format_campaign_send_summary,
    get_campaign,
    list_campaigns,
    parse_schedule_window,
    rename_campaign,
    run_campaign_once,
    schedule_campaign_first_send,
    set_campaign_chats,
    update_campaign_interval,
    update_campaign_schedule,
    update_campaign_template,
)
from app.services.templates import list_templates
from app.states import CampaignEdit

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("campaign_detail_"))
async def callback_campaign_detail(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = get_campaign(session, campaign_id)
        if not campaign:
            await query.message.edit_text("Кампания не найдена.")
            await query.answer()
            return
        await query.message.edit_text(
            format_campaign_card(campaign),
            reply_markup=get_campaign_detail_keyboard(campaign.id),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.regexp(r"^campaign_edit_\d+$"))
async def callback_campaign_edit_menu(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = get_campaign(session, campaign_id)
        if not campaign:
            await query.message.edit_text("Кампания не найдена.")
            await query.answer()
            return
        await query.message.edit_text(
            f"<b>Edit Campaign</b>\n\n{format_campaign_card(campaign)}",
            reply_markup=get_campaign_edit_keyboard(campaign.id),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_edit_template_"))
async def callback_campaign_change_template(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = get_campaign(session, campaign_id)
        if not campaign:
            await query.message.edit_text("Кампания не найдена.")
            await query.answer()
            return
        templates = list_templates(session, include_inactive=False)
        if not templates:
            await query.message.edit_text(
                "Нет активных шаблонов.",
                reply_markup=get_campaign_edit_keyboard(campaign_id),
            )
            await query.answer()
            return
        await query.message.edit_text(
            "Выберите новый шаблон.\n\nИзменение применится к следующей отправке.",
            reply_markup=get_campaign_template_keyboard(templates, campaign_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_set_template_"))
async def callback_campaign_set_template(query: CallbackQuery):
    parts = query.data.split("_")
    campaign_id = int(parts[3])
    template_id = int(parts[4])
    session = get_session()
    try:
        campaign = update_campaign_template(session, campaign_id, template_id)
        await query.message.edit_text(
            "Шаблон кампании обновлён.\n\n"
            "Новая версия будет использована при следующей отправке.\n\n"
            "Кампания настроена. Выполнить первую отправку сейчас?",
            reply_markup=get_campaign_first_send_keyboard(campaign.id),
        )
    except Exception as exc:
        logger.error("campaign edit template failed: %s", exc, exc_info=True)
        await query.message.edit_text(
            f"Не удалось обновить шаблон.\n\nПричина: {exc}",
            reply_markup=get_campaign_edit_keyboard(campaign_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_edit_interval_"))
async def callback_campaign_interval_start(query: CallbackQuery, state: FSMContext):
    campaign_id = int(query.data.split("_")[-1])
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignEdit.waiting_for_interval)
    await query.message.edit_text(
        "Введите новый интервал отправки в минутах.\n\n"
        "Допустимо: 1–1440.\n"
        "Изменение начнёт работать со следующего цикла планировщика.",
        reply_markup=get_campaign_edit_keyboard(campaign_id),
    )
    await query.answer()


@router.message(CampaignEdit.waiting_for_interval)
async def process_campaign_interval(message: Message, state: FSMContext):
    data = await state.get_data()
    campaign_id = int(data["campaign_id"])
    session = get_session()
    try:
        campaign = update_campaign_interval(session, campaign_id, int(message.text.strip()))
        await state.clear()
        await message.answer(
            f"Интервал обновлён: {campaign.interval_minutes} мин.\n\n"
            "Кампания настроена. Выполнить первую отправку сейчас?",
            reply_markup=get_campaign_first_send_keyboard(campaign.id),
        )
    except Exception as exc:
        await message.answer(
            f"Не удалось обновить интервал.\n\nПричина: {exc}",
            reply_markup=get_campaign_edit_keyboard(campaign_id),
        )
    finally:
        session.close()


@router.callback_query(F.data.startswith("campaign_edit_rename_"))
async def callback_campaign_rename_start(query: CallbackQuery, state: FSMContext):
    campaign_id = int(query.data.split("_")[-1])
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignEdit.waiting_for_name)
    await query.message.edit_text(
        "Введите новое название кампании.",
        reply_markup=get_campaign_edit_keyboard(campaign_id),
    )
    await query.answer()


@router.message(CampaignEdit.waiting_for_name)
async def process_campaign_name(message: Message, state: FSMContext):
    data = await state.get_data()
    campaign_id = int(data["campaign_id"])
    session = get_session()
    try:
        campaign = rename_campaign(session, campaign_id, message.text)
        await state.clear()
        await message.answer(
            "Название кампании обновлено.",
            reply_markup=get_campaign_edit_keyboard(campaign.id),
        )
    except Exception as exc:
        await message.answer(
            f"Не удалось переименовать кампанию.\n\nПричина: {exc}",
            reply_markup=get_campaign_edit_keyboard(campaign_id),
        )
    finally:
        session.close()


@router.callback_query(F.data.startswith("campaign_edit_chats_"))
async def callback_campaign_chats_start(query: CallbackQuery, state: FSMContext):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = get_campaign(session, campaign_id)
        if not campaign:
            await query.message.edit_text("Кампания не найдена.")
            await query.answer()
            return
        selected_ids = {chat.id for chat in campaign.chats}
        chats = session.query(Chat).filter(
            Chat.advertising_account_id == campaign.account_id,
            Chat.is_active == True,  # noqa: E712
        ).order_by(Chat.title.asc()).all()
        await state.update_data(
            campaign_id=campaign.id,
            selected_chat_ids=sorted(selected_ids),
        )
        await state.set_state(CampaignEdit.managing_chats)
        await query.message.edit_text(
            "Выберите чаты кампании.\n\n"
            "Текущие назначения сохранятся до подтверждения.",
            reply_markup=get_campaign_chats_keyboard(chats, campaign.id, selected_ids),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(CampaignEdit.managing_chats, F.data.startswith("campaign_toggle_chat_"))
async def callback_campaign_toggle_chat(query: CallbackQuery, state: FSMContext):
    parts = query.data.split("_")
    campaign_id = int(parts[3])
    chat_id = int(parts[4])
    data = await state.get_data()
    selected_ids = set(data.get("selected_chat_ids", []))
    if chat_id in selected_ids:
        selected_ids.remove(chat_id)
    else:
        selected_ids.add(chat_id)
    await state.update_data(selected_chat_ids=sorted(selected_ids))

    session = get_session()
    try:
        campaign = get_campaign(session, campaign_id)
        chats = session.query(Chat).filter(
            Chat.advertising_account_id == campaign.account_id,
            Chat.is_active == True,  # noqa: E712
        ).order_by(Chat.title.asc()).all()
        await query.message.edit_text(
            "Выберите чаты кампании.\n\n"
            "Текущие назначения сохранятся до подтверждения.",
            reply_markup=get_campaign_chats_keyboard(chats, campaign_id, selected_ids),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(CampaignEdit.managing_chats, F.data.startswith("campaign_confirm_chats_"))
async def callback_campaign_confirm_chats(query: CallbackQuery, state: FSMContext):
    campaign_id = int(query.data.split("_")[-1])
    data = await state.get_data()
    selected_ids = data.get("selected_chat_ids", [])
    await state.set_state(CampaignEdit.confirming_chats)
    await query.message.edit_text(
        "Подтвердите изменение списка чатов.\n\n"
        f"Будет назначено чатов: {len(selected_ids)}.\n"
        "Это изменит состав кампании.",
        reply_markup=get_campaign_destructive_confirmation_keyboard(campaign_id),
    )
    await query.answer()


@router.callback_query(CampaignEdit.confirming_chats, F.data.startswith("campaign_save_chats_"))
async def callback_campaign_save_chats(query: CallbackQuery, state: FSMContext):
    campaign_id = int(query.data.split("_")[-1])
    data = await state.get_data()
    selected_ids = data.get("selected_chat_ids", [])
    session = get_session()
    try:
        campaign = set_campaign_chats(session, campaign_id, selected_ids)
        await state.clear()
        await query.message.edit_text(
            "Список чатов кампании обновлён.\n\n"
            "Кампания настроена. Выполнить первую отправку сейчас?",
            reply_markup=get_campaign_first_send_keyboard(campaign.id),
        )
    except Exception as exc:
        logger.error("campaign chat assignment failed: %s", exc, exc_info=True)
        await query.message.edit_text(
            f"Не удалось обновить чаты.\n\nПричина: {exc}",
            reply_markup=get_campaign_edit_keyboard(campaign_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_edit_schedule_"))
async def callback_campaign_schedule_menu(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    await query.message.edit_text(
        "Настройка расписания.\n\n"
        "Можно включить отправку на весь день или временно выключить расписание.",
        reply_markup=get_campaign_schedule_keyboard(campaign_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("campaign_schedule_window_"))
async def callback_campaign_schedule_window(query: CallbackQuery, state: FSMContext):
    campaign_id = int(query.data.split("_")[-1])
    await state.update_data(campaign_id=campaign_id)
    await state.set_state(CampaignEdit.waiting_for_schedule)
    await query.message.edit_text(
        "Введите окно отправки в формате HH:MM-HH:MM.\n\n"
        "Пример: 09:00-18:30",
        reply_markup=get_campaign_schedule_keyboard(campaign_id),
    )
    await query.answer()


@router.message(CampaignEdit.waiting_for_schedule)
async def process_campaign_schedule_window(message: Message, state: FSMContext):
    data = await state.get_data()
    campaign_id = int(data["campaign_id"])
    session = get_session()
    try:
        start_time, end_time = parse_schedule_window(message.text)
        campaign = update_campaign_schedule(
            session,
            campaign_id,
            enabled=True,
            start_time=start_time,
            end_time=end_time,
        )
        await state.clear()
        await message.answer(
            f"Расписание обновлено: {start_time}–{end_time}.\n\n"
            "Кампания настроена. Выполнить первую отправку сейчас?",
            reply_markup=get_campaign_first_send_keyboard(campaign.id),
        )
    except Exception as exc:
        await message.answer(
            f"Не удалось обновить расписание.\n\nПричина: {exc}",
            reply_markup=get_campaign_schedule_keyboard(campaign_id),
        )
    finally:
        session.close()


@router.callback_query(F.data.startswith("campaign_schedule_all_day_"))
async def callback_campaign_schedule_all_day(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = update_campaign_schedule(
            session,
            campaign_id,
            enabled=True,
            start_time=None,
            end_time=None,
        )
        await query.message.edit_text(
            "Расписание включено на весь день.\n\n"
            "Кампания настроена. Выполнить первую отправку сейчас?",
            reply_markup=get_campaign_first_send_keyboard(campaign.id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_schedule_disable_"))
async def callback_campaign_schedule_disable(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = update_campaign_schedule(session, campaign_id, enabled=False)
        await query.message.edit_text(
            "Расписание кампании выключено.",
            reply_markup=get_campaign_edit_keyboard(campaign.id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_first_now_"))
async def callback_campaign_first_send_now(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    await _run_campaign_send_and_report(query, campaign_id)


@router.callback_query(F.data.startswith("campaign_send_now_"))
async def callback_campaign_manual_send(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    await _run_campaign_send_and_report(query, campaign_id)


@router.callback_query(F.data.startswith("campaign_first_5min_"))
async def callback_campaign_first_send_5min(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = schedule_campaign_first_send(session, campaign_id, 5)
        first_send = campaign.first_send_at.strftime("%H:%M") if campaign.first_send_at else "—"
        await query.message.edit_text(
            f"Первая отправка запланирована через 5 минут.\n\n"
            f"Время: {first_send}\n"
            "После этого кампания продолжит работать по обычному интервалу.",
            reply_markup=get_campaign_detail_keyboard(campaign.id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("campaign_first_regular_"))
async def callback_campaign_first_send_regular(query: CallbackQuery):
    campaign_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaign = schedule_campaign_first_send(session, campaign_id, None)
        await query.message.edit_text(
            "Кампания будет работать по обычному интервалу.",
            reply_markup=get_campaign_detail_keyboard(campaign.id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("account_campaign_test_"))
async def callback_account_campaign_test(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        campaigns = [
            campaign
            for campaign in list_campaigns(session, include_inactive=True)
            if campaign.account_id == account_id
        ]
        if not campaigns:
            await query.message.edit_text(
                "Для этого аккаунта нет кампаний.",
            )
            await query.answer()
            return
        await query.message.edit_text(
            "Выберите кампанию для тестовой отправки.",
            reply_markup=get_account_campaign_test_keyboard(campaigns, account_id),
        )
    finally:
        session.close()
    await query.answer()


async def _run_campaign_send_and_report(query: CallbackQuery, campaign_id: int) -> None:
    session = get_session()
    try:
        summary = await run_campaign_once(session, campaign_id, ignore_cooldown=True)
        await query.message.edit_text(
            format_campaign_send_summary(summary),
            reply_markup=get_campaign_detail_keyboard(campaign_id),
        )
    except Exception as exc:
        logger.error("campaign manual send failed: %s", exc, exc_info=True)
        await query.message.edit_text(
            f"Не удалось выполнить тестовую отправку.\n\nПричина: {exc}",
            reply_markup=get_campaign_detail_keyboard(campaign_id),
        )
    finally:
        session.close()
    await query.answer()
