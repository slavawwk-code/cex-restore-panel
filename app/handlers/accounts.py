import logging
from html import escape
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.states import AccountCreation
from app.keyboards.accounts import (
    get_accounts_menu,
    get_accounts_list_keyboard,
    get_account_detail_keyboard,
    get_account_creation_keyboard,
    get_account_confirmation_keyboard,
    get_account_settings_keyboard,
    get_account_subpage_keyboard,
)
from app.database import get_session
from app.services.accounts import (
    create_account,
    list_accounts,
    get_account,
    update_account_status,
    disable_account,
    get_account_by_phone,
)
from app.scheduler import SchedulerService
from app.services.account_health import calculate_account_health
from app.ui.cards import (
    SEPARATOR,
    account_status,
    format_account_card,
    format_account_health_card,
    format_accounts_list,
)

router = Router()
logger = logging.getLogger(__name__)
scheduler_service: SchedulerService | None = None


def set_scheduler(service: SchedulerService) -> None:
    global scheduler_service
    scheduler_service = service


def _scheduler_running() -> bool:
    return bool(scheduler_service and scheduler_service.running)


@router.callback_query(F.data == "accounts_list")
async def callback_accounts_menu(query: CallbackQuery):
    """Handle accounts menu callback."""
    await query.message.edit_text(
        "<b>Аккаунты</b>\n\nУправление рекламными аккаунтами.",
        reply_markup=get_accounts_menu(),
        parse_mode="HTML",
    )
    await query.answer()


@router.callback_query(F.data == "accounts_view")
async def callback_view_accounts(query: CallbackQuery):
    """View all advertising accounts."""
    session = get_session()
    try:
        accounts = list_accounts(session)

        if not accounts:
            await query.message.edit_text(
                "<b>Аккаунты</b>\n\nАккаунтов пока нет.",
                reply_markup=get_accounts_menu(),
                parse_mode="HTML",
            )
            await query.answer()
            return

        account_health = [
            (account, calculate_account_health(session, account, _scheduler_running()))
            for account in accounts
        ]
        scores = {account.id: health.score for account, health in account_health}
        await query.message.edit_text(
            format_accounts_list(account_health),
            reply_markup=get_accounts_list_keyboard(accounts, scores),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("account_detail_"))
async def callback_account_detail(query: CallbackQuery):
    """Show account detail."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = get_account(session, account_id)

        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return

        health = calculate_account_health(session, account, _scheduler_running())

        await query.message.edit_text(
            format_account_card(account, health),
            reply_markup=get_account_detail_keyboard(account_id, account.status, account.session_connected),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("account_health_"))
async def callback_account_health(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        health = calculate_account_health(session, account, _scheduler_running())
        await query.message.edit_text(
            format_account_health_card(account, health),
            reply_markup=get_account_subpage_keyboard(account_id),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("account_settings_"))
async def callback_account_settings(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        text = (
            f"<b>Настройки · {escape(account.display_name)}</b>\n\n"
            f"{SEPARATOR}\n\n"
            f"Статус\n{account_status(account)}\n\n"
            f"Telegram\n{'🟢 Подключён' if account.session_connected else '🔴 Не подключён'}\n\n"
            f"{SEPARATOR}"
        )
        await query.message.edit_text(
            text,
            reply_markup=get_account_settings_keyboard(
                account_id, account.status, account.session_connected
            ),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "account_add")
async def callback_add_account_start(query: CallbackQuery, state: FSMContext):
    """Start account creation flow."""
    await state.set_state(AccountCreation.waiting_for_display_name)
    await query.message.edit_text(
        "Новый аккаунт\n\n"
        "Введите понятное название аккаунта.\n"
        "Например: «Основной» или «Аккаунт 2».",
        reply_markup=get_account_creation_keyboard(),
    )
    await query.answer()


@router.message(AccountCreation.waiting_for_display_name)
async def process_display_name(message: Message, state: FSMContext):
    """Process display name input."""
    display_name = message.text.strip()

    if not display_name or len(display_name) < 2:
        await message.answer("🔴 Название должно содержать минимум 2 символа:")
        return

    if len(display_name) > 50:
        await message.answer("🔴 Название не должно превышать 50 символов:")
        return

    await state.update_data(display_name=display_name)
    await state.set_state(AccountCreation.waiting_for_phone_number)
    await message.answer(
        f"🟢 Название: {display_name}\n\n"
        "Введите номер телефона в международном формате.\n"
        "Например: +79123456789."
    )


@router.message(AccountCreation.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext):
    """Process phone number input."""
    phone_number = message.text.strip()

    if not phone_number:
        await message.answer("🔴 Номер телефона не может быть пустым:")
        return

    if len(phone_number) < 5 or len(phone_number) > 20:
        await message.answer("🔴 Номер должен содержать от 5 до 20 символов:")
        return

    session = get_session()
    try:
        if get_account_by_phone(session, phone_number):
            await message.answer(
                "🔴 Аккаунт с таким номером уже существует. Введите другой номер:"
            )
            return
    finally:
        session.close()

    await state.update_data(phone_number=phone_number)
    await state.set_state(AccountCreation.waiting_for_session_name)
    await message.answer(
        f"🟢 Номер: {phone_number}\n\n"
        "Введите внутреннее имя сессии латиницей.\n"
        "Например: session_1 или main."
    )


@router.message(AccountCreation.waiting_for_session_name)
async def process_session_name(message: Message, state: FSMContext):
    """Process session name input."""
    session_name = message.text.strip().replace(" ", "_").lower()

    if not session_name or len(session_name) < 2:
        await message.answer("🔴 Имя сессии должно содержать минимум 2 символа:")
        return

    if len(session_name) > 30:
        await message.answer("🔴 Имя сессии не должно превышать 30 символов:")
        return

    if not session_name.replace("_", "").isalnum():
        await message.answer("🔴 Используйте только латинские буквы, цифры и подчёркивание:")
        return

    data = await state.get_data()
    display_name = data["display_name"]
    phone_number = data["phone_number"]

    text = (
        "Проверьте данные аккаунта\n\n"
        f"Название: {display_name}\n"
        f"Номер: {phone_number}\n"
        f"Сессия: {session_name}\n\n"
        "Всё верно?"
    )

    await state.update_data(session_name=session_name)
    await state.set_state(AccountCreation.confirmation)
    await message.answer(text, reply_markup=get_account_confirmation_keyboard())


@router.callback_query(AccountCreation.confirmation, F.data.startswith("account_confirm_"))
async def confirm_account_creation(query: CallbackQuery, state: FSMContext):
    """Confirm and create the account."""
    data = await state.get_data()
    session = get_session()

    try:
        account = create_account(
            session,
            display_name=data["display_name"],
            phone_number=data["phone_number"],
            telethon_session=data["session_name"],
        )

        await state.clear()
        await query.message.edit_text(
            f"🟢 Аккаунт создан\n\n"
            f"{account.display_name}\n"
            f"{account.phone_number}\n"
            f"🟡 Статус: прогрев\n\n"
            "Теперь настройте прокси и подключите Telegram-сессию.",
            reply_markup=get_accounts_menu(),
        )
    except Exception as e:
        logger.error(f"Error creating account: {e}", exc_info=True)
        await query.message.edit_text(
            "🔴 Не удалось создать аккаунт. Проверьте введённые данные.",
            reply_markup=get_accounts_menu(),
        )
    finally:
        session.close()

    await query.answer()


@router.callback_query(F.data.startswith("account_pause_"))
async def callback_pause_account(query: CallbackQuery):
    """Pause an account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "paused"):
            await query.answer("⚪ Аккаунт приостановлен")
            await callback_account_detail(query)
        else:
            await query.answer("🔴 Не удалось приостановить аккаунт", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_resume_"))
async def callback_resume_account(query: CallbackQuery):
    """Resume a paused account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "active"):
            await query.answer("🟢 Аккаунт возобновлён")
            await callback_account_detail(query)
        else:
            await query.answer("🔴 Не удалось возобновить аккаунт", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_activate_"))
async def callback_activate_account(query: CallbackQuery):
    """Activate an account from warming state."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "active"):
            await query.answer("🟢 Аккаунт активирован")
            await callback_account_detail(query)
        else:
            await query.answer("🔴 Не удалось активировать аккаунт", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_warming_"))
async def callback_warming_account(query: CallbackQuery):
    """Set account to warming state."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "warming"):
            await query.answer("🟡 Аккаунт переведён на прогрев")
            await callback_account_detail(query)
        else:
            await query.answer("🔴 Не удалось изменить статус", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_disable_"))
async def callback_disable_account(query: CallbackQuery):
    """Disable an account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if disable_account(session, account_id):
            await query.answer("⚪ Аккаунт отключён")
            await callback_account_detail(query)
        else:
            await query.answer("🔴 Не удалось отключить аккаунт", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_chats_"))
async def callback_account_chats(query: CallbackQuery):
    """Show chats assigned to an account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return

        chats = account.chats
        if not chats:
            text = (
                f"<b>Чаты · {escape(account.display_name)}</b>\n\n"
                f"{SEPARATOR}\n\nЧаты пока не назначены.\n\n{SEPARATOR}"
            )
        else:
            lines = [f"<b>Чаты · {escape(account.display_name)}</b>", "", SEPARATOR, ""]
            for chat in chats:
                status_emoji = {"active": "🟢", "paused": "⚪", "error": "🔴"}.get(chat.status, "🟡")
                lines.extend(
                    [
                        escape(chat.title),
                        f"{status_emoji} · интервал {chat.cooldown_minutes} мин.",
                    ]
                )
                if chat.last_error:
                    lines.append(escape(chat.last_error[:120]))
                lines.append("")
            lines.append(SEPARATOR)
            text = "\n".join(lines)

        await query.message.edit_text(
            text,
            reply_markup=get_account_subpage_keyboard(account_id),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()
