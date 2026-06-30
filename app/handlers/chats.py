import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.states import ChatCreation, ChatEdit
from app.keyboards.chats import (
    get_chats_menu,
    get_chats_list_keyboard,
    get_accounts_selection_keyboard,
    get_templates_selection_keyboard,
    get_chat_creation_cancel_keyboard,
    get_chat_confirmation_keyboard,
    get_chat_detail_keyboard,
    get_accounts_selection_for_change,
    get_templates_selection_for_change,
    get_chat_cooldown_cancel_keyboard,
    get_chat_error_keyboard,
)
from app.database import get_session
from app.database.models import Template
from app.services.chats import (
    create_chat,
    list_chats,
    get_chat,
    get_chat_info,
    update_chat_account,
    update_chat_template,
    update_chat_cooldown,
    update_chat_status,
    disable_chat,
    get_status_emoji,
)
from app.services.accounts import list_accounts, get_account
from app.services.templates import list_templates

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "chats_list")
async def callback_chats_menu(query: CallbackQuery):
    """Handle chats menu callback."""
    await query.message.edit_text(
        "💬 Управление чатами\n\nВыберите действие:",
        reply_markup=get_chats_menu(),
    )
    await query.answer()


@router.callback_query(F.data == "chats_view")
async def callback_view_chats(query: CallbackQuery):
    """View all chats."""
    session = get_session()
    try:
        chats = list_chats(session, include_inactive=False)

        if not chats:
            await query.message.edit_text(
                "💬 Чаты\n\nЧатов пока нет.\n\nДобавьте первый чат.",
                reply_markup=get_chats_menu(),
            )
            await query.answer()
            return

        text = "💬 Чаты\n\n"
        for chat in chats:
            emoji = get_status_emoji(chat.status)
            account_name = chat.account.display_name if chat.account else "неизвестно"
            template_name = chat.template.name if chat.template else "не назначен"

            text += f"{emoji} {chat.title}\n"
            text += f"   📱 {account_name} • 📝 {template_name}\n"
            text += f"   ⏱️ {chat.cooldown_minutes} мин."

            if chat.last_sent_at:
                text += f" • 📅 {chat.last_sent_at.strftime('%d.%m.%Y %H:%M')}"
            else:
                text += " • Отправок не было"
            text += "\n\n"

        await query.message.edit_text(text, reply_markup=get_chats_list_keyboard(chats))
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_detail_"))
async def callback_chat_detail(query: CallbackQuery):
    """Show chat detail."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        info = get_chat_info(session, chat_id)
        if not info:
            await query.answer("❌ Чат не найден", show_alert=True)
            return

        emoji = get_status_emoji(info["status"])
        text = "💬 Карточка чата\n\n"
        text += f"{emoji} {info['title']}\n\n"
        text += f"ID чата: {info['username_or_chat_id']}\n"
        text += f"📱 Аккаунт: {info['account_name']}\n"
        text += f"📝 Шаблон: {info['template_name']}\n"
        text += f"⏱️ Интервал: {info['cooldown_minutes']} мин.\n"
        text += f"📅 Создан: {info['created_at'].strftime('%d.%m.%Y %H:%M')}\n"

        if info["last_sent_at"]:
            text += f"📤 Последняя отправка: {info['last_sent_at'].strftime('%d.%m.%Y %H:%M')}\n"
        else:
            text += "📤 Отправок не было\n"

        if info["last_error"]:
            text += f"\n⚠️ Ошибка: {info['last_error'][:100]}\n"

        await query.message.edit_text(
            text,
            reply_markup=get_chat_detail_keyboard(chat_id, info["status"]),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "chat_create")
async def callback_create_chat_step1(query: CallbackQuery, state: FSMContext):
    """Start chat creation - step 1: select account."""
    session = get_session()
    try:
        accounts = list_accounts(session)
        active_accounts = [a for a in accounts if a.status == "active"]

        if not active_accounts:
            await query.message.edit_text(
                "❌ Нет активных аккаунтов.\n\nСначала создайте и активируйте аккаунт.",
                reply_markup=get_chats_menu(),
            )
            await query.answer()
            return

        await state.set_state(ChatCreation.selecting_account)
        await query.message.edit_text(
            "💬 Новый чат\n\n"
            "Шаг 1 из 5: выберите рекламный аккаунт:",
            reply_markup=get_accounts_selection_keyboard(active_accounts),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(ChatCreation.selecting_account, F.data.startswith("create_chat_account_"))
async def callback_create_chat_step2(query: CallbackQuery, state: FSMContext):
    """Step 2: select template."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = get_account(session, account_id)
        if not account:
            await query.answer("❌ Аккаунт не найден", show_alert=True)
            return

        templates = list_templates(session, include_inactive=False)
        if not templates:
            await query.message.edit_text(
                "❌ Нет активных шаблонов.\n\nСначала создайте шаблон.",
                reply_markup=get_chats_menu(),
            )
            await query.answer()
            return

        await state.update_data(account_id=account_id, account_name=account.display_name)
        await state.set_state(ChatCreation.selecting_template)
        await query.message.edit_text(
            "💬 Новый чат\n\n"
            "Шаг 2 из 5: выберите шаблон\n\n"
            f"Аккаунт: {account.display_name}",
            reply_markup=get_templates_selection_keyboard(templates),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(ChatCreation.selecting_template, F.data.startswith("create_chat_template_"))
async def callback_create_chat_step3(query: CallbackQuery, state: FSMContext):
    """Step 3: enter chat username or ID."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        template = session.query(Template).filter(Template.id == template_id).first()
        if not template:
            await query.answer("❌ Шаблон не найден", show_alert=True)
            return

        await state.update_data(template_id=template_id, template_name=template.name)
        await state.set_state(ChatCreation.entering_username)
        await query.message.edit_text(
            "💬 Новый чат\n\n"
            "Шаг 3 из 5: введите @username или ID чата.\n"
            "Например: @groupname или -100123456789.",
            reply_markup=get_chat_creation_cancel_keyboard(),
        )
    finally:
        session.close()
    await query.answer()


@router.message(ChatCreation.entering_username)
async def process_chat_username(message: Message, state: FSMContext):
    """Process chat username/ID input."""
    username = message.text.strip()

    if not username:
        await message.answer("❌ Username или ID чата не может быть пустым:")
        return

    if len(username) < 3:
        await message.answer("❌ Username или ID чата указан неверно:")
        return

    if len(username) > 50:
        await message.answer("❌ Username или ID чата слишком длинный:")
        return

    if username.startswith("@"):
        if not re.match(r"^@[a-zA-Z0-9_]{3,32}$", username):
            await message.answer(
                "❌ Неверный формат. Используйте @username из латинских букв, цифр и подчёркиваний:"
            )
            return
    else:
        if not username.lstrip("-").isdigit():
            await message.answer(
                "❌ Используйте @username или отрицательный числовой ID, например -100123456789:"
            )
            return

    await state.update_data(username_or_chat_id=username)
    await state.set_state(ChatCreation.entering_title)
    await message.answer(
        f"✅ Чат: {username}\n\n"
        "Шаг 4 из 5: введите понятное название чата (2–100 символов):"
    )


@router.message(ChatCreation.entering_title)
async def process_chat_title(message: Message, state: FSMContext):
    """Process chat display name input."""
    title = message.text.strip()

    if not title or len(title) < 2:
        await message.answer("❌ Название должно содержать минимум 2 символа:")
        return

    if len(title) > 100:
        await message.answer("❌ Название не должно превышать 100 символов:")
        return

    await state.update_data(title=title)
    await state.set_state(ChatCreation.entering_cooldown)
    await message.answer(
        f"✅ Название: {title}\n\n"
        "Шаг 5 из 5: укажите интервал между сообщениями в минутах (1–1440):"
    )


@router.message(ChatCreation.entering_cooldown)
async def process_chat_cooldown(message: Message, state: FSMContext):
    """Process cooldown input."""
    try:
        cooldown = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число:")
        return

    if cooldown < 1 or cooldown > 1440:
        await message.answer("❌ Интервал должен быть от 1 до 1440 минут:")
        return

    data = await state.get_data()
    account_name = data["account_name"]
    template_name = data["template_name"]
    title = data["title"]
    username = data["username_or_chat_id"]

    confirmation_text = (
        "📋 Проверьте настройки чата\n\n"
        f"📱 Аккаунт: {account_name}\n"
        f"📝 Шаблон: {template_name}\n"
        f"💬 Чат: {title}\n"
        f"ID: {username}\n"
        f"⏱️ Интервал: {cooldown} мин.\n"
        "🟢 Статус: активен\n\n"
        "Всё верно?"
    )

    await state.update_data(cooldown=cooldown)
    await state.set_state(ChatCreation.confirmation)
    await message.answer(confirmation_text, reply_markup=get_chat_confirmation_keyboard())


@router.callback_query(ChatCreation.confirmation, F.data == "chat_confirm_create")
async def confirm_chat_creation(query: CallbackQuery, state: FSMContext):
    """Confirm and create the chat."""
    data = await state.get_data()
    session = get_session()

    try:
        chat = create_chat(
            session,
            advertising_account_id=data["account_id"],
            template_id=data["template_id"],
            title=data["title"],
            username_or_chat_id=data["username_or_chat_id"],
            cooldown_minutes=data["cooldown"],
        )

        await state.clear()
        await query.message.edit_text(
            f"✅ Чат создан\n\n"
            f"💬 {chat.title}\n"
            f"📱 {data['account_name']}\n"
            f"📝 {data['template_name']}\n"
            f"⏱️ {data['cooldown']} мин.\n\n"
            "Чат добавлен в расписание.",
            reply_markup=get_chats_menu(),
        )
    except Exception as e:
        logger.error(f"Error creating chat: {e}", exc_info=True)
        await query.message.edit_text(
            "❌ Не удалось создать чат.",
            reply_markup=get_chats_menu(),
        )
    finally:
        session.close()

    await query.answer()


@router.callback_query(F.data.startswith("chat_pause_"))
async def callback_pause_chat(query: CallbackQuery):
    """Pause a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_chat_status(session, chat_id, "paused"):
            await query.answer("✅ Чат приостановлен")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Не удалось приостановить чат", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_resume_"))
async def callback_resume_chat(query: CallbackQuery):
    """Resume a paused chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_chat_status(session, chat_id, "active"):
            await query.answer("✅ Чат возобновлён")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Не удалось возобновить чат", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_change_account_"))
async def callback_change_chat_account(query: CallbackQuery):
    """Change the account for a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        accounts = list_accounts(session)
        active_accounts = [a for a in accounts if a.status == "active"]

        if not active_accounts:
            await query.answer("❌ Нет активных аккаунтов", show_alert=True)
            return

        await query.message.edit_text(
            "💬 Смена аккаунта\n\nВыберите новый аккаунт:",
            reply_markup=get_accounts_selection_for_change(active_accounts, chat_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_set_account_"))
async def callback_set_chat_account(query: CallbackQuery):
    """Set the selected account."""
    parts = query.data.split("_")
    chat_id = int(parts[3])
    account_id = int(parts[4])
    session = get_session()

    try:
        if update_chat_account(session, chat_id, account_id):
            await query.answer("✅ Аккаунт изменён")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Не удалось изменить аккаунт", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_change_template_"))
async def callback_change_chat_template(query: CallbackQuery):
    """Change the template for a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        templates = list_templates(session, include_inactive=False)

        if not templates:
            await query.answer("❌ Нет активных шаблонов", show_alert=True)
            return

        await query.message.edit_text(
            "💬 Смена шаблона\n\nВыберите новый шаблон:",
            reply_markup=get_templates_selection_for_change(templates, chat_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_set_template_"))
async def callback_set_chat_template(query: CallbackQuery):
    """Set the selected template."""
    parts = query.data.split("_")
    chat_id = int(parts[3])
    template_id = int(parts[4])
    session = get_session()

    try:
        if update_chat_template(session, chat_id, template_id):
            await query.answer("✅ Шаблон изменён")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Не удалось изменить шаблон", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_change_cooldown_"))
async def callback_change_cooldown(query: CallbackQuery, state: FSMContext):
    """Start cooldown change."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        chat = get_chat(session, chat_id)
        if not chat:
            await query.answer("❌ Чат не найден", show_alert=True)
            return

        await state.set_state(ChatEdit.changing_cooldown)
        await state.update_data(chat_id=chat_id)
        await query.message.edit_text(
            "💬 Изменение интервала\n\n"
            f"Текущий интервал: {chat.cooldown_minutes} мин.\n\n"
            "Введите новый интервал (1–1440 минут):",
            reply_markup=get_chat_cooldown_cancel_keyboard(chat_id),
        )
    finally:
        session.close()
    await query.answer()


@router.message(ChatEdit.changing_cooldown)
async def process_new_cooldown(message: Message, state: FSMContext):
    """Process new cooldown input."""
    try:
        cooldown = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число:")
        return

    if cooldown < 1 or cooldown > 1440:
        await message.answer("❌ Интервал должен быть от 1 до 1440 минут:")
        return

    data = await state.get_data()
    chat_id = data["chat_id"]
    session = get_session()

    try:
        if update_chat_cooldown(session, chat_id, cooldown):
            await state.clear()
            await message.answer("✅ Интервал обновлён")
        else:
            await message.answer("❌ Не удалось обновить интервал")
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_error_"))
async def callback_view_chat_error(query: CallbackQuery):
    """View chat error message."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        chat = get_chat(session, chat_id)
        if not chat:
            await query.answer("❌ Чат не найден", show_alert=True)
            return

        if not chat.last_error:
            await query.message.edit_text(
                "✅ Для этого чата ошибок не записано.",
                reply_markup=get_chat_error_keyboard(chat_id),
            )
        else:
            await query.message.edit_text(
                f"⚠️ Последняя ошибка\n\n{chat.last_error}",
                reply_markup=get_chat_error_keyboard(chat_id),
            )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_disable_"))
async def callback_disable_chat(query: CallbackQuery):
    """Disable a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if disable_chat(session, chat_id):
            await query.answer("✅ Чат отключён")
            await callback_view_chats(query)
        else:
            await query.answer("❌ Не удалось отключить чат", show_alert=True)
    finally:
        session.close()


@router.callback_query(ChatCreation.entering_username, F.data == "chats_list")
@router.callback_query(ChatCreation.entering_title, F.data == "chats_list")
@router.callback_query(ChatCreation.entering_cooldown, F.data == "chats_list")
@router.callback_query(ChatCreation.confirmation, F.data == "chats_list")
async def cancel_chat_creation(query: CallbackQuery, state: FSMContext):
    """Cancel chat creation."""
    await state.clear()
    await callback_chats_menu(query)
