import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import load_settings
from app.database import get_session
from app.database.models import AdvertisingAccount
from app.services.account_lifecycle_manager import (
    AccountLifecycleError,
    account_lifecycle_manager,
)

router = Router()
logger = logging.getLogger(__name__)


def _is_owner(user_id: int) -> bool:
    return user_id == load_settings(require_secrets=False).owner_telegram_id


def _parse_account_id(message: Message) -> int | None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        return None
    return int(parts[1].strip())


def _confirmation_keyboard(action: str, account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить",
                    callback_data=f"lifecycle_{action}_confirm_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"account_detail_{account_id}",
                )
            ],
        ]
    )


def _account_name(account_id: int) -> str | None:
    session = get_session()
    try:
        account = session.get(AdvertisingAccount, account_id)
        return account.display_name if account else None
    finally:
        session.close()


async def _command_prompt(message: Message, action: str) -> None:
    if not _is_owner(message.from_user.id):
        await message.answer("🔴 Эта операция доступна только владельцу.")
        return
    account_id = _parse_account_id(message)
    if account_id is None:
        await message.answer(f"Использование: /account_{action} ACCOUNT_ID")
        return
    name = _account_name(account_id)
    if name is None:
        await message.answer("🔴 Аккаунт не найден.")
        return
    labels = {
        "delete": "полностью удалить",
        "disable": "отключить",
        "reauth": "сбросить авторизацию",
    }
    await message.answer(
        f"Подтвердите действие: {labels[action]} аккаунт «{name}» (ID {account_id}).",
        reply_markup=_confirmation_keyboard(action, account_id),
    )


@router.message(Command("account_delete"))
async def command_delete_account(message: Message):
    await _command_prompt(message, "delete")


@router.message(Command("account_disable"))
async def command_disable_account(message: Message):
    await _command_prompt(message, "disable")


@router.message(Command("account_reauth"))
async def command_reauth_account(message: Message):
    await _command_prompt(message, "reauth")


@router.callback_query(F.data.startswith("lifecycle_delete_prompt_"))
async def callback_delete_prompt(query: CallbackQuery):
    await _callback_prompt(query, "delete")


@router.callback_query(F.data.startswith("lifecycle_reauth_prompt_"))
async def callback_reauth_prompt(query: CallbackQuery):
    await _callback_prompt(query, "reauth")


async def _callback_prompt(query: CallbackQuery, action: str) -> None:
    if not _is_owner(query.from_user.id):
        await query.answer("Операция доступна только владельцу", show_alert=True)
        return
    account_id = int(query.data.split("_")[-1])
    name = _account_name(account_id)
    if name is None:
        await query.answer("Аккаунт не найден", show_alert=True)
        return
    label = "полностью удалить" if action == "delete" else "сбросить авторизацию"
    await query.message.edit_text(
        f"Подтвердите действие: {label} аккаунт «{name}» (ID {account_id}).",
        reply_markup=_confirmation_keyboard(action, account_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("lifecycle_delete_confirm_"))
async def callback_delete_confirm(query: CallbackQuery):
    if not _is_owner(query.from_user.id):
        await query.answer("Операция доступна только владельцу", show_alert=True)
        return
    account_id = int(query.data.split("_")[-1])
    try:
        result = await account_lifecycle_manager.delete_account(account_id)
    except AccountLifecycleError as error:
        await query.answer(str(error), show_alert=True)
        return
    text = "Аккаунт полностью удалён."
    if result.result == "partial":
        text += f"\n\nSession-файл требует ручной очистки: {result.reason}"
    await query.message.edit_text(text)
    await query.answer()


@router.callback_query(F.data.startswith("lifecycle_disable_confirm_"))
async def callback_disable_confirm(query: CallbackQuery):
    if not _is_owner(query.from_user.id):
        await query.answer("Операция доступна только владельцу", show_alert=True)
        return
    account_id = int(query.data.split("_")[-1])
    try:
        await account_lifecycle_manager.disable_account(account_id)
    except AccountLifecycleError as error:
        await query.answer(str(error), show_alert=True)
        return
    await query.message.edit_text("Аккаунт отключён. Session-файл сохранён.")
    await query.answer()


@router.callback_query(F.data.startswith("lifecycle_reauth_confirm_"))
async def callback_reauth_confirm(query: CallbackQuery, state: FSMContext):
    if not _is_owner(query.from_user.id):
        await query.answer("Операция доступна только владельцу", show_alert=True)
        return
    account_id = int(query.data.split("_")[-1])
    try:
        await account_lifecycle_manager.reauth_account(account_id)
    except AccountLifecycleError as error:
        await query.answer(str(error), show_alert=True)
        return
    await state.clear()
    await query.message.edit_text(
        "Авторизация сброшена безопасно. Session-файл помещён в архив.\n\n"
        "Откройте Telegram-настройки аккаунта и начните вход заново.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Перейти к авторизации",
                        callback_data=f"auth_methods_{account_id}",
                    )
                ]
            ]
        ),
    )
    await query.answer()

