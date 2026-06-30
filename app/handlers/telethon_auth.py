import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from telethon.errors import SessionPasswordNeededError

from app.database import get_session
from app.database.models import AdvertisingAccount
from app.keyboards.telethon_auth import (
    get_auth_confirmation_keyboard,
    get_code_input_cancel_keyboard,
    get_disconnect_confirmation_keyboard,
)
from app.services.telethon_auth import (
    TelethonAuthError,
    check_session_status,
    disconnect_session,
    send_login_code,
    sign_in_with_code,
    sign_in_with_password,
)
from app.states import TelethonAuth

router = Router()
logger = logging.getLogger(__name__)


def _get_account(session, account_id: int) -> AdvertisingAccount | None:
    return (
        session.query(AdvertisingAccount)
        .filter(AdvertisingAccount.id == account_id)
        .first()
    )


@router.callback_query(F.data.startswith("auth_connect_"))
async def callback_auth_connect(query: CallbackQuery, state: FSMContext):
    """Start authentication flow."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("❌ Аккаунт не найден", show_alert=True)
            return
        if not account.phone_number:
            await query.message.edit_text(
                "❌ Для аккаунта не указан номер телефона."
            )
            await query.answer()
            return

        await state.set_state(TelethonAuth.confirming_phone)
        await state.update_data(
            account_id=account_id, phone_number=account.phone_number
        )
        route = (
            f"через {account.proxy_type}-прокси {account.proxy_host}:{account.proxy_port}"
            if account.proxy_enabled
            else "напрямую, без прокси"
        )
        await query.message.edit_text(
            "🔗 Подключение Telegram-аккаунта\n\n"
            f"Номер: {account.phone_number}\n"
            f"Соединение: {route}\n\n"
            "Telegram сам выберет способ доставки кода. Обычно код приходит "
            "служебным сообщением в официальное приложение Telegram.",
            reply_markup=get_auth_confirmation_keyboard(account_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("auth_send_code_"))
async def callback_auth_send_code(query: CallbackQuery, state: FSMContext):
    """Request a login code and report Telegram's delivery channel."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("❌ Аккаунт не найден", show_alert=True)
            return

        await query.message.edit_text("⏳ Запрашиваем код у Telegram…")
        try:
            result = await send_login_code(account)
            if result["already_authorized"]:
                await check_session_status(session, account)
                account.last_error = None
                session.commit()
                await state.clear()
                await query.message.edit_text(
                    "✅ Сохранённая сессия уже авторизована.\n\n"
                    "Telegram-аккаунт подключён, новый код не требуется.",
                    reply_markup=get_code_input_cancel_keyboard(account_id),
                )
            else:
                await state.update_data(
                    phone_code_hash=result["phone_code_hash"],
                    delivery=result["delivery"],
                )
                await state.set_state(TelethonAuth.waiting_for_code)
                timeout_text = (
                    f" Код действует около {result['timeout']} сек."
                    if result.get("timeout")
                    else ""
                )
                await query.message.edit_text(
                    "✅ Telegram принял запрос.\n\n"
                    f"Код отправлен {result['delivery']}.{timeout_text}\n"
                    "Введите полученный код цифрами без лишнего текста.",
                    reply_markup=get_code_input_cancel_keyboard(account_id),
                )
        except TelethonAuthError as error:
            account.last_error = str(error)
            session.commit()
            await state.clear()
            await query.message.edit_text(
                f"❌ Не удалось получить код\n\n{error}\n\n"
                "Проверьте номер телефона, сеть и настройки прокси.",
                reply_markup=get_code_input_cancel_keyboard(account_id),
            )
    finally:
        session.close()
    await query.answer()


@router.message(TelethonAuth.waiting_for_code)
async def process_login_code(message: Message, state: FSMContext):
    """Process login code input."""
    code = (message.text or "").replace(" ", "").replace("-", "")
    if not code.isdigit() or len(code) not in {4, 5, 6}:
        await message.answer("❌ Введите код из 4–6 цифр без другого текста:")
        return

    data = await state.get_data()
    account_id = data["account_id"]
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await message.answer("❌ Аккаунт не найден")
            await state.clear()
            return

        await message.answer("⏳ Проверяем код…")
        try:
            await sign_in_with_code(account, code, data["phone_code_hash"])
            await check_session_status(session, account)
            account.last_error = None
            session.commit()
            await state.clear()
            await message.answer(
                "✅ Telegram-аккаунт успешно подключён.\n\n"
                "Сессия сохранена и готова к работе."
            )
            logger.info("Account %s authenticated successfully", account_id)
        except SessionPasswordNeededError:
            await state.set_state(TelethonAuth.waiting_for_password)
            await message.answer(
                "🔐 На аккаунте включена двухэтапная аутентификация.\n\n"
                "Введите облачный пароль Telegram:"
            )
        except TelethonAuthError as error:
            account.last_error = str(error)
            session.commit()
            await message.answer(f"❌ {error}\n\nПопробуйте ещё раз.")
    finally:
        session.close()


@router.message(TelethonAuth.waiting_for_password)
async def process_2fa_password(message: Message, state: FSMContext):
    """Process 2FA password without logging or retaining it in bot messages."""
    password = message.text or ""
    if not password:
        await message.answer("❌ Пароль не может быть пустым:")
        return

    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete operator message containing 2FA password")

    data = await state.get_data()
    account_id = data["account_id"]
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await message.answer("❌ Аккаунт не найден")
            await state.clear()
            return

        await message.answer("⏳ Проверяем пароль…")
        try:
            await sign_in_with_password(account, password)
            await check_session_status(session, account)
            account.last_error = None
            session.commit()
            await state.clear()
            await message.answer(
                "✅ Двухэтапная аутентификация пройдена.\n\n"
                "Telegram-аккаунт успешно подключён."
            )
            logger.info("Account %s 2FA authenticated successfully", account_id)
        except TelethonAuthError as error:
            account.last_error = str(error)
            session.commit()
            await message.answer(f"❌ {error}\n\nПопробуйте ещё раз.")
    finally:
        password = ""
        session.close()


@router.callback_query(F.data.startswith("auth_check_status_"))
async def callback_auth_check_status(query: CallbackQuery):
    """Check and display session status."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("❌ Аккаунт не найден", show_alert=True)
            return

        await query.message.edit_text("⏳ Проверяем сессию Telegram…")
        status = await check_session_status(session, account)
        if status["connected"]:
            text = (
                "✅ Сессия подключена\n\n"
                f"Пользователь: {status.get('username') or status.get('user_id')}\n"
                f"ID: {status.get('user_id')}"
            )
        else:
            text = (
                "❌ Сессия не подключена\n\n"
                f"Причина: {status.get('reason', 'неизвестно')}"
            )
        await query.message.edit_text(
            text, reply_markup=get_code_input_cancel_keyboard(account_id)
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("auth_disconnect_"))
async def callback_auth_disconnect(query: CallbackQuery):
    """Confirm disconnect."""
    account_id = int(query.data.split("_")[-1])
    await query.message.edit_text(
        "⚠️ Отключить Telegram-сессию?\n\n"
        "Локальный файл сессии будет удалён. Подключить аккаунт снова можно в любое время.",
        reply_markup=get_disconnect_confirmation_keyboard(account_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("auth_confirm_disconnect_"))
async def callback_auth_confirm_disconnect(query: CallbackQuery):
    """Confirm and disconnect."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("❌ Аккаунт не найден", show_alert=True)
            return
        await query.message.edit_text("⏳ Отключаем сессию…")
        if await disconnect_session(session, account, delete_file=True):
            await query.message.edit_text(
                "✅ Telegram-сессия отключена.",
                reply_markup=get_code_input_cancel_keyboard(account_id),
            )
        else:
            await query.message.edit_text(
                "❌ Не удалось отключить сессию.",
                reply_markup=get_code_input_cancel_keyboard(account_id),
            )
    finally:
        session.close()
    await query.answer()
