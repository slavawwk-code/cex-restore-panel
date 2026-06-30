import logging
from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.database.models import AdvertisingAccount
from app.keyboards.telethon_auth import (
    get_auth_confirmation_keyboard,
    get_auth_cancel_keyboard,
    get_auth_methods_keyboard,
    get_code_input_cancel_keyboard,
    get_disconnect_confirmation_keyboard,
)
from app.services.account_sessions import (
    AccountSessionError,
    resolve_session_source,
    session_source_label,
)
from app.services.account_orchestrator import (
    OrchestratorError,
    account_orchestrator,
)
from app.services.telethon_auth import TelethonAuthError
from app.states import TelethonAuth
from app.ui.cards import orchestration_status

router = Router()
logger = logging.getLogger(__name__)


def _get_account(session, account_id: int) -> AdvertisingAccount | None:
    return (
        session.query(AdvertisingAccount)
        .filter(AdvertisingAccount.id == account_id)
        .first()
    )


@router.callback_query(F.data.startswith("auth_methods_"))
async def callback_auth_methods(query: CallbackQuery, state: FSMContext):
    """Show all supported account session methods."""
    account_id = int(query.data.split("_")[-1])
    await state.clear()
    session = get_session()
    try:
        account = _get_account(session, account_id)
        if not account:
            await query.answer("🔴 Аккаунт не найден", show_alert=True)
            return
        try:
            resolution = resolve_session_source(account)
            source = session_source_label(account)
        except AccountSessionError:
            resolution = None
            source = "ошибка конфигурации"
        status = {
            "active": "🟢 active",
            "banned": "🔴 banned",
            "error": "🔴 error",
            "unverified": "🟡 unverified",
        }.get(account.auth_status or "unverified", "🟡 unverified")
        text = (
            "<b>Telegram-сессия</b>\n\n"
            f"Источник\n{source}\n\n"
            f"Статус\n{status}\n\n"
            f"Состояние управления\n{orchestration_status(account)}\n\n"
            f"Health\n{account.health_score or 0}%\n\n"
            f"Последняя проверка\n"
            f"{account.last_health_check.strftime('%d.%m.%Y %H:%M') if account.last_health_check else '—'}\n\n"
            f"Ошибка\n{escape(account.last_auth_error) if account.last_auth_error else '—'}"
        )
        await query.message.edit_text(
            text,
            reply_markup=get_auth_methods_keyboard(
                account_id,
                bool(account.session_connected),
                resolution is not None,
            ),
            parse_mode="HTML",
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("auth_import_"))
async def callback_auth_import(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.set_state(TelethonAuth.waiting_for_session_file)
    await state.update_data(account_id=account_id)
    await query.message.edit_text(
        "Загрузите Telethon-файл с расширением .session.\n\n"
        "Файл будет проверен через Telegram до сохранения. Максимальный размер — 10 МБ.",
        reply_markup=get_auth_cancel_keyboard(account_id),
    )
    await query.answer()


@router.message(TelethonAuth.waiting_for_session_file)
async def process_session_file(message: Message, state: FSMContext):
    if not message.document:
        await message.answer("🔴 Отправьте файл .session как документ.")
        return
    if message.document.file_size and message.document.file_size > 10 * 1024 * 1024:
        await message.answer("🔴 Файл превышает 10 МБ.")
        return

    data = await state.get_data()
    account_id = data["account_id"]
    buffer = BytesIO()
    try:
        await message.bot.download(message.document, destination=buffer)
        payload = buffer.getvalue()
    except Exception:
        await message.answer("🔴 Не удалось скачать файл из Telegram.")
        return
    finally:
        buffer.close()

    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete operator message containing session file")

    try:
        await message.answer("Проверяем session-файл через Telegram…")
        try:
            result = await account_orchestrator.import_session(
                account_id,
                message.document.file_name or "uploaded.session",
                payload,
            )
        except (AccountSessionError, OrchestratorError) as error:
            await message.answer(f"🔴 {error}\n\nОтправьте другой .session файл.")
            return
        except Exception:
            logger.exception("Session import orchestration failed")
            await message.answer("🔴 Не удалось импортировать сессию. Повторите позже.")
            return
        await state.clear()
        await message.answer(
            "🟢 Session-файл импортирован.\n\n"
            f"Пользователь: {result.get('username') or result.get('user_id')}\n"
            "Файл сохранён с правами 600 и назначен основным источником."
        )
    finally:
        payload = b""


@router.callback_query(F.data.startswith("auth_string_"))
async def callback_auth_string(query: CallbackQuery, state: FSMContext):
    account_id = int(query.data.split("_")[-1])
    await state.set_state(TelethonAuth.waiting_for_string_session)
    await state.update_data(account_id=account_id)
    await query.message.edit_text(
        "Вставьте StringSession одним сообщением.\n\n"
        "Значение будет удалено из чата после получения и сохранено как fallback.",
        reply_markup=get_auth_cancel_keyboard(account_id),
    )
    await query.answer()


@router.message(TelethonAuth.waiting_for_string_session)
async def process_string_session(message: Message, state: FSMContext):
    value = message.text or ""
    try:
        await message.delete()
    except Exception:
        logger.warning("Could not delete operator message containing StringSession")
    data = await state.get_data()
    account_id = data["account_id"]
    try:
        try:
            result = await account_orchestrator.import_string_session(
                account_id, value
            )
        except (AccountSessionError, OrchestratorError) as error:
            await message.answer(f"🔴 {error}\n\nОтправьте другую StringSession.")
            return
        except Exception:
            logger.exception("StringSession orchestration failed")
            await message.answer("🔴 Не удалось проверить StringSession. Повторите позже.")
            return
        await state.clear()
        await message.answer(
            "🟢 StringSession проверена и сохранена.\n\n"
            f"Пользователь: {result.get('username') or result.get('user_id')}"
        )
    finally:
        value = ""


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
    await query.message.edit_text("⏳ Запрашиваем код у Telegram…")
    try:
        result = await account_orchestrator.login_account(account_id)
        if result["already_authorized"]:
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
    except (TelethonAuthError, OrchestratorError) as error:
        await state.clear()
        await query.message.edit_text(
            f"❌ Не удалось получить код\n\n{error}\n\n"
            "Проверьте номер телефона, сеть и настройки прокси.",
            reply_markup=get_code_input_cancel_keyboard(account_id),
        )
    except Exception:
        logger.exception("Login request orchestration failed")
        await state.clear()
        await query.message.edit_text(
            "❌ Внутренняя ошибка управления авторизацией.",
            reply_markup=get_code_input_cancel_keyboard(account_id),
        )
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
    try:
        await message.answer("⏳ Проверяем код…")
        try:
            result = await account_orchestrator.login_account(
                account_id,
                action="code",
                code=code,
                phone_code_hash=data["phone_code_hash"],
            )
            if result.get("requires_password"):
                await state.set_state(TelethonAuth.waiting_for_password)
                await message.answer(
                    "🔐 На аккаунте включена двухэтапная аутентификация.\n\n"
                    "Введите облачный пароль Telegram:"
                )
                return
            await state.clear()
            await message.answer(
                "✅ Telegram-аккаунт успешно подключён.\n\n"
                "Сессия сохранена и готова к работе."
            )
            logger.info("Account %s authenticated successfully", account_id)
        except (TelethonAuthError, OrchestratorError) as error:
            await message.answer(f"❌ {error}\n\nПопробуйте ещё раз.")
    finally:
        code = ""


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
    try:
        await message.answer("⏳ Проверяем пароль…")
        try:
            await account_orchestrator.login_account(
                account_id,
                action="password",
                password=password,
            )
            await state.clear()
            await message.answer(
                "✅ Двухэтапная аутентификация пройдена.\n\n"
                "Telegram-аккаунт успешно подключён."
            )
            logger.info("Account %s 2FA authenticated successfully", account_id)
        except (TelethonAuthError, OrchestratorError) as error:
            await message.answer(f"❌ {error}\n\nПопробуйте ещё раз.")
    finally:
        password = ""


@router.callback_query(F.data.startswith("auth_check_status_"))
async def callback_auth_check_status(query: CallbackQuery):
    """Check and display session status."""
    account_id = int(query.data.split("_")[-1])
    await query.message.edit_text("⏳ Проверяем сессию Telegram…")
    status = await account_orchestrator.validate_account(account_id)
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
    await query.message.edit_text("⏳ Отключаем сессию…")
    try:
        if await account_orchestrator.disconnect_account(
            account_id, delete_file=True
        ):
            await query.message.edit_text(
                "✅ Telegram-сессия отключена.",
                reply_markup=get_code_input_cancel_keyboard(account_id),
            )
        else:
            await query.message.edit_text(
                "❌ Не удалось отключить сессию.",
                reply_markup=get_code_input_cancel_keyboard(account_id),
            )
    except Exception:
        logger.exception("Session disconnect orchestration failed")
        await query.message.edit_text(
            "❌ Не удалось отключить сессию.",
            reply_markup=get_code_input_cancel_keyboard(account_id),
        )
    await query.answer()
