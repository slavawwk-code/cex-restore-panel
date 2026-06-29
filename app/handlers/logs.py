import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.keyboards.logs import (
    get_logs_menu,
    get_accounts_selection_for_logs,
    get_chats_selection_for_logs,
    get_logs_back_keyboard,
)
from app.database import get_session
from app.database.models import AdvertisingAccount, Chat
from app.services.logs import (
    list_recent_logs,
    list_error_logs,
    list_success_logs,
    list_logs_by_account,
    list_logs_by_chat,
    format_logs_list,
)

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "logs_menu")
async def callback_logs_menu(query: CallbackQuery):
    """Handle logs menu callback."""
    await query.message.edit_text(
        "📋 Logs\n\nView send history and errors.",
        reply_markup=get_logs_menu(),
    )
    await query.answer()


@router.callback_query(F.data == "logs_recent")
async def callback_logs_recent(query: CallbackQuery):
    """Show recent logs."""
    session = get_session()
    try:
        logs = list_recent_logs(session, limit=20)
        text = format_logs_list(logs, "📋 Recent Logs (Last 20)")

        await query.message.edit_text(text, reply_markup=get_logs_back_keyboard())
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "logs_errors")
async def callback_logs_errors(query: CallbackQuery):
    """Show error logs."""
    session = get_session()
    try:
        logs = list_error_logs(session, limit=20)
        text = format_logs_list(logs, "❌ Error Logs (Last 20)")

        await query.message.edit_text(text, reply_markup=get_logs_back_keyboard())
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "logs_success")
async def callback_logs_success(query: CallbackQuery):
    """Show success logs."""
    session = get_session()
    try:
        logs = list_success_logs(session, limit=20)
        text = format_logs_list(logs, "✅ Success Logs (Last 20)")

        await query.message.edit_text(text, reply_markup=get_logs_back_keyboard())
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "logs_by_account")
async def callback_logs_by_account(query: CallbackQuery):
    """Choose account for logs."""
    session = get_session()
    try:
        accounts = session.query(AdvertisingAccount).order_by(AdvertisingAccount.display_name).all()

        if not accounts:
            await query.message.edit_text(
                "❌ No accounts found.",
                reply_markup=get_logs_back_keyboard(),
            )
            await query.answer()
            return

        await query.message.edit_text(
            "📱 Select Account\n\nChoose an account to see its logs:",
            reply_markup=get_accounts_selection_for_logs(accounts),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("logs_account_"))
async def callback_logs_account_selected(query: CallbackQuery):
    """Show logs for selected account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()

        if not account:
            await query.answer("❌ Account not found", show_alert=True)
            return

        logs = list_logs_by_account(session, account_id, limit=20)
        text = format_logs_list(logs, f"📱 Logs for {account.display_name} (Last 20)")

        await query.message.edit_text(text, reply_markup=get_logs_back_keyboard())
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "logs_by_chat")
async def callback_logs_by_chat(query: CallbackQuery):
    """Choose chat for logs."""
    session = get_session()
    try:
        chats = (
            session.query(Chat)
            .filter(Chat.is_active == True)
            .order_by(Chat.title)
            .all()
        )

        if not chats:
            await query.message.edit_text(
                "❌ No chats found.",
                reply_markup=get_logs_back_keyboard(),
            )
            await query.answer()
            return

        await query.message.edit_text(
            "💬 Select Chat\n\nChoose a chat to see its logs:",
            reply_markup=get_chats_selection_for_logs(chats),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("logs_chat_"))
async def callback_logs_chat_selected(query: CallbackQuery):
    """Show logs for selected chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        chat = session.query(Chat).filter(Chat.id == chat_id).first()

        if not chat:
            await query.answer("❌ Chat not found", show_alert=True)
            return

        logs = list_logs_by_chat(session, chat_id, limit=20)
        text = format_logs_list(logs, f"💬 Logs for {chat.title} (Last 20)")

        await query.message.edit_text(text, reply_markup=get_logs_back_keyboard())
    finally:
        session.close()
    await query.answer()
