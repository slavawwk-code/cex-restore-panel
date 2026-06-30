import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.database.models import AdvertisingAccount
from app.keyboards.proxy import (
    get_proxy_cancel_keyboard,
    get_proxy_confirmation_keyboard,
    get_proxy_detection_confirmation_keyboard,
    get_full_diagnostics_keyboard,
    get_proxy_menu_keyboard,
    get_proxy_history_keyboard,
    get_proxy_saved_keyboard,
    get_proxy_setup_method_keyboard,
    get_proxy_skip_keyboard,
    get_proxy_type_keyboard,
)
from app.services.proxy import (
    ProxyConfigurationError,
    ParsedProxy,
    ProxyStringParseError,
    configure_proxy,
    detect_working_proxy_type,
    disable_proxy,
    format_proxy_confirmation,
    format_proxy_diagnostics,
    format_proxy_detection_failure,
    format_proxy_status_card,
    get_proxy_history,
    parse_proxy_string,
    save_detected_proxy,
    run_fast_proxy_check,
    run_full_proxy_diagnostics,
)
from app.states import ProxySetup
from app.ui.cards import format_proxy_history

router = Router()
logger = logging.getLogger(__name__)

PASTE_PROXY_HELP = (
    "Вставьте прокси одной строкой.\n\n"
    "Поддерживаемые форматы:\n\n"
    "host:port\n"
    "host:port:login:password\n"
    "login:password@host:port\n"
    "http://login:password@host:port\n"
    "https://login:password@host:port\n"
    "socks4://login:password@host:port\n"
    "socks5://login:password@host:port\n\n"
    "Пример:\n"
    "138.249.176.42:64799:username:password"
)


def _get_account(session, account_id: int) -> AdvertisingAccount | None:
    return (
        session.query(AdvertisingAccount)
        .filter(AdvertisingAccount.id == account_id)
        .first()
    )


def _proxy_status_text(account: AdvertisingAccount) -> str:
    return format_proxy_status_card(account)


@router.callback_query(F.data.startswith("proxy_menu_"))
async def callback_proxy_menu(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.clear()
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        await query.message.edit_text(
            _proxy_status_text(account),
            reply_markup=get_proxy_menu_keyboard(account_id, account.proxy_enabled),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("proxy_setup_"))
async def callback_proxy_setup(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.clear()
    await state.update_data(account_id=account_id)
    await query.message.edit_text(
        "Настройка прокси\n\nВыберите способ настройки.",
        reply_markup=get_proxy_setup_method_keyboard(account_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("proxy_paste_"))
async def callback_proxy_paste(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.set_state(ProxySetup.entering_string)
    await state.update_data(account_id=account_id)
    await query.message.edit_text(
        PASTE_PROXY_HELP,
        reply_markup=get_proxy_cancel_keyboard(account_id),
    )
    await query.answer()


@router.message(ProxySetup.entering_string)
async def process_proxy_string(message: Message, state: FSMContext):
    raw_value = message.text or ""
    await _delete_sensitive_message(message)
    try:
        parsed = parse_proxy_string(raw_value)
    except ProxyStringParseError as error:
        await message.answer(
            "🔴 Не удалось распознать формат прокси.\n\n"
            f"Причина: {error}\n\n"
            "Поддерживаются:\n"
            "host:port\n"
            "host:port:user:password\n"
            "user:password@host:port\n"
            "http://…\n"
            "https://…\n"
            "socks4://…\n"
            "socks5://…"
        )
        return

    data = await state.get_data()
    account_id = data["account_id"]
    await state.update_data(
        proxy_type=parsed.proxy_type,
        host=parsed.host,
        port=parsed.port,
        username=parsed.username,
        password=parsed.password,
        candidate_types=list(parsed.candidate_types),
        paste_mode=True,
    )
    await _show_proxy_confirmation(message, state, account_id)


async def _delete_sensitive_message(message: Message) -> None:
    """Best-effort removal of operator messages containing proxy credentials."""
    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete operator message containing proxy credentials")


@router.callback_query(F.data.startswith("proxy_manual_"))
async def callback_proxy_manual(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.set_state(ProxySetup.selecting_type)
    await state.update_data(account_id=account_id)
    await query.message.edit_text(
        "Ручная настройка\n\nВыберите тип прокси:",
        reply_markup=get_proxy_type_keyboard(account_id),
    )
    await query.answer()


@router.callback_query(
    ProxySetup.selecting_type, F.data.startswith("proxy_type_")
)
async def callback_proxy_type(query: CallbackQuery, state: FSMContext):
    parts = query.data.split("_")
    account_id = int(parts[2])
    proxy_type = parts[3]
    await state.update_data(
        proxy_type=proxy_type,
        candidate_types=[proxy_type],
        paste_mode=False,
    )
    await state.set_state(ProxySetup.entering_host)
    await query.message.edit_text(
        f"Тип: {proxy_type}\n\nВведите IP-адрес или домен прокси:",
        reply_markup=get_proxy_cancel_keyboard(account_id),
    )
    await query.answer()


@router.message(ProxySetup.entering_host)
async def process_proxy_host(message: Message, state: FSMContext):
    host = (message.text or "").strip()
    data = await state.get_data()
    account_id = data["account_id"]
    if not host or len(host) > 255 or any(char.isspace() for char in host):
        await message.answer("🔴 Укажите корректный IP-адрес или домен прокси:")
        return
    await state.update_data(host=host)
    await state.set_state(ProxySetup.entering_port)
    await message.answer(
        "Введите порт прокси (от 1 до 65535):",
        reply_markup=get_proxy_cancel_keyboard(account_id),
    )


@router.message(ProxySetup.entering_port)
async def process_proxy_port(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data["account_id"]
    try:
        port = int((message.text or "").strip())
    except ValueError:
        await message.answer("🔴 Порт должен быть числом от 1 до 65535:")
        return
    if port < 1 or port > 65535:
        await message.answer("🔴 Порт должен быть от 1 до 65535:")
        return
    await state.update_data(port=port)
    await state.set_state(ProxySetup.entering_username)
    await message.answer(
        "Введите логин прокси или нажмите «Пропустить»:",
        reply_markup=get_proxy_skip_keyboard(account_id, "username"),
    )


@router.message(ProxySetup.entering_username)
async def process_proxy_username(message: Message, state: FSMContext):
    username = (message.text or "").strip()
    if len(username) > 255:
        await message.answer("🔴 Логин слишком длинный. Введите другой:")
        return
    data = await state.get_data()
    account_id = data["account_id"]
    await state.update_data(username=username or None)
    await state.set_state(ProxySetup.entering_password)
    await message.answer(
        "Введите пароль прокси или нажмите «Пропустить».\n"
        "Пароль не будет показан в интерфейсе и логах.",
        reply_markup=get_proxy_skip_keyboard(account_id, "password"),
    )


@router.callback_query(
    ProxySetup.entering_username, F.data.startswith("proxy_skip_username_")
)
async def callback_skip_username(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.update_data(username=None)
    await state.set_state(ProxySetup.entering_password)
    await query.message.edit_text(
        "Введите пароль прокси или нажмите «Пропустить».\n"
        "Пароль не будет показан в интерфейсе и логах.",
        reply_markup=get_proxy_skip_keyboard(account_id, "password"),
    )
    await query.answer()


async def _show_proxy_confirmation(
    message: Message, state: FSMContext, account_id: int
) -> None:
    data = await state.get_data()
    await state.set_state(ProxySetup.confirmation)
    proxy_config = _proxy_config_from_data(data)
    keyboard = (
        get_proxy_detection_confirmation_keyboard(account_id)
        if data.get("paste_mode")
        else get_proxy_confirmation_keyboard(account_id)
    )
    await message.answer(
        format_proxy_confirmation(proxy_config),
        reply_markup=keyboard,
    )


def _proxy_config_from_data(data: dict) -> ParsedProxy:
    proxy_type = data.get("proxy_type")
    candidate_types = tuple(
        data.get("candidate_types")
        or ([proxy_type] if proxy_type else ["SOCKS5", "HTTP", "SOCKS4"])
    )
    return ParsedProxy(
        proxy_type=proxy_type,
        host=data["host"],
        port=data["port"],
        username=data.get("username"),
        password=data.get("password"),
        candidate_types=candidate_types,
    )


@router.message(ProxySetup.entering_password)
async def process_proxy_password(message: Message, state: FSMContext):
    password = message.text or ""
    await _delete_sensitive_message(message)
    if len(password) > 255:
        await message.answer("🔴 Пароль слишком длинный. Введите другой:")
        return
    data = await state.get_data()
    account_id = data["account_id"]
    await state.update_data(password=password or None)
    await _show_proxy_confirmation(message, state, account_id)


@router.callback_query(
    ProxySetup.entering_password, F.data.startswith("proxy_skip_password_")
)
async def callback_skip_password(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.update_data(password=None)
    data = await state.get_data()
    await state.set_state(ProxySetup.confirmation)
    proxy_config = _proxy_config_from_data(data)
    await query.message.edit_text(
        format_proxy_confirmation(proxy_config),
        reply_markup=get_proxy_confirmation_keyboard(account_id),
    )
    await query.answer()


@router.callback_query(
    ProxySetup.confirmation, F.data.startswith("proxy_save_test_")
)
async def callback_proxy_save_and_test(query: CallbackQuery, state: FSMContext):
    """Detect a pasted proxy type against Telegram, then persist success."""
    account_id = int(query.data.split("_")[-1])
    data = await state.get_data()
    proxy_config = _proxy_config_from_data(data)
    types_to_test = proxy_config.candidate_types

    # Callback queries expire quickly; acknowledge before network tests begin.
    await query.answer()
    await query.message.edit_text(
        "🔍 Проверяю прокси…\n\nПробую:\n" + "\n".join(types_to_test)
    )
    detection = await detect_working_proxy_type(
        proxy_config,
        candidate_types=types_to_test,
    )

    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.message.edit_text("🔴 Аккаунт не найден")
            await state.clear()
            return
        if detection.success:
            save_detected_proxy(session, account, proxy_config, detection)
            await state.clear()
            await query.message.edit_text(
                format_proxy_status_card(account)
                + "\n\n"
                + format_proxy_diagnostics(detection),
                reply_markup=get_proxy_menu_keyboard(account_id, True),
                parse_mode="HTML",
            )
        else:
            await query.message.edit_text(
                format_proxy_detection_failure(detection),
                reply_markup=get_proxy_detection_confirmation_keyboard(account_id),
            )
    finally:
        session.close()


@router.callback_query(ProxySetup.confirmation, F.data.startswith("proxy_save_"))
async def callback_proxy_save(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    data = await state.get_data()
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        configure_proxy(
            session,
            account,
            data["proxy_type"],
            data["host"],
            data["port"],
            data.get("username"),
            data.get("password"),
        )
        await state.clear()
        await query.message.edit_text(
            "🟢 Прокси сохранён.\n\nПроверить соединение?",
            reply_markup=get_proxy_saved_keyboard(account_id),
        )
    except ProxyConfigurationError as error:
        await query.answer(f"🔴 {error}", show_alert=True)
        return
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("proxy_fast_"))
async def callback_proxy_fast_check(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        if not account.proxy_type:
            await query.answer()
            await query.message.edit_text(
                "🟡 Тип прокси ещё не определён.\n\n"
                "Сначала выполните полную диагностику.",
                reply_markup=get_full_diagnostics_keyboard(account_id),
            )
            return
        # Acknowledge immediately because Telethon connection tests may take time.
        await query.answer()
        await query.message.edit_text("🟢 Выполняю быструю проверку…")
        await run_fast_proxy_check(session, account)
        await query.message.edit_text(
            format_proxy_status_card(account),
            reply_markup=get_proxy_menu_keyboard(account_id, account.proxy_enabled),
            parse_mode="HTML",
        )
    finally:
        session.close()


@router.callback_query(F.data.startswith("proxy_diagnostics_"))
async def callback_proxy_diagnostics(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        candidate_types = (
            ("SOCKS5", "HTTP", "SOCKS4")
            if account.proxy_detected_type or not account.proxy_type
            else (account.proxy_type,)
        )
        await query.answer()
        await query.message.edit_text(
            "🔍 Выполняю полную диагностику…\n\nПробую:\n"
            + "\n".join(candidate_types)
        )
        detection = await run_full_proxy_diagnostics(session, account)
        await query.message.edit_text(
            format_proxy_status_card(account)
            + "\n\n"
            + format_proxy_diagnostics(detection),
            reply_markup=get_proxy_menu_keyboard(account_id, account.proxy_enabled),
            parse_mode="HTML",
        )
    finally:
        session.close()


@router.callback_query(F.data.startswith("proxy_history_"))
async def callback_proxy_history(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        records = get_proxy_history(session, account_id)
        await query.message.edit_text(
            format_proxy_history(account, records),
            reply_markup=get_proxy_history_keyboard(account_id),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("proxy_disable_"))
async def callback_proxy_disable(query: CallbackQuery):
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        disable_proxy(session, account)
        await query.message.edit_text(
            "⚪ Прокси отключён. Подключения этого аккаунта будут идти напрямую.",
            reply_markup=get_proxy_menu_keyboard(account_id, False),
        )
    finally:
        session.close()
    await query.answer()
