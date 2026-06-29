import logging
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
)
from app.keyboards.main import get_back_button
from app.database import get_session
from app.database.models import AdvertisingAccount
from app.services.accounts import (
    create_account,
    list_accounts,
    get_account,
    update_account_status,
    count_account_chats,
    disable_account,
    get_account_by_phone,
)

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "accounts_list")
async def callback_accounts_menu(query: CallbackQuery):
    """Handle accounts menu callback."""
    await query.message.edit_text(
        "📊 Accounts Management\n\nWhat would you like to do?",
        reply_markup=get_accounts_menu(),
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
                "📊 Accounts\n\nNo accounts yet.\n\nCreate one to get started.",
                reply_markup=get_accounts_menu(),
            )
            await query.answer()
            return

        text = "📊 Accounts\n\n"
        for account in accounts:
            status_emoji = {
                "active": "🟢",
                "paused": "⏸️",
                "warming": "🔥",
                "disabled": "🚫",
            }.get(account.status, "❓")

            chat_count = count_account_chats(session, account.id)
            text += f"{status_emoji} {account.display_name}\n"
            text += f"   📱 {account.phone_number}\n"
            text += f"   💬 {chat_count} chats\n\n"

        await query.message.edit_text(text, reply_markup=get_accounts_list_keyboard(accounts))
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
            await query.answer("❌ Account not found", show_alert=True)
            return

        chat_count = count_account_chats(session, account_id)

        status_emoji = {
            "active": "🟢",
            "paused": "⏸️",
            "warming": "🔥",
            "disabled": "🚫",
        }.get(account.status, "❓")

        text = f"📊 Account Details\n\n"
        text += f"{status_emoji} {account.display_name}\n"
        text += f"📱 Phone: {account.phone_number}\n"
        text += f"💬 Assigned Chats: {chat_count}\n"
        text += f"📅 Created: {account.created_at.strftime('%Y-%m-%d %H:%M')}\n"

        # Session status
        text += f"\n🔗 Telegram Session\n"
        if account.session_connected:
            text += f"✅ Connected\n"
            if account.session_username:
                text += f"📱 @{account.session_username}\n"
            if account.session_user_id:
                text += f"🆔 ID: {account.session_user_id}\n"
            if account.session_last_checked_at:
                text += f"✓ Last checked: {account.session_last_checked_at.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            text += f"❌ Not connected\n"

        if account.last_error:
            text += f"\n⚠️ Last Error:\n{account.last_error}\n"

        await query.message.edit_text(
            text,
            reply_markup=get_account_detail_keyboard(account_id, account.status, account.session_connected),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "account_add")
async def callback_add_account_start(query: CallbackQuery, state: FSMContext):
    """Start account creation flow."""
    await state.set_state(AccountCreation.waiting_for_display_name)
    await query.message.edit_text(
        "📝 Create New Account\n\n"
        "What is the display name for this account?\n"
        "(e.g., 'Main Account', 'Account 2')",
        reply_markup=get_account_creation_keyboard(),
    )
    await query.answer()


@router.message(AccountCreation.waiting_for_display_name)
async def process_display_name(message: Message, state: FSMContext):
    """Process display name input."""
    display_name = message.text.strip()

    if not display_name or len(display_name) < 2:
        await message.answer("❌ Display name must be at least 2 characters long. Try again:")
        return

    if len(display_name) > 50:
        await message.answer("❌ Display name must be 50 characters or less. Try again:")
        return

    await state.update_data(display_name=display_name)
    await state.set_state(AccountCreation.waiting_for_phone_number)
    await message.answer(
        f"✅ Display name: {display_name}\n\n"
        "What is the phone number for this account?\n"
        "(e.g., +1234567890, +7912345678)"
    )


@router.message(AccountCreation.waiting_for_phone_number)
async def process_phone_number(message: Message, state: FSMContext):
    """Process phone number input."""
    phone_number = message.text.strip()

    if not phone_number:
        await message.answer("❌ Phone number cannot be empty. Try again:")
        return

    if len(phone_number) < 5 or len(phone_number) > 20:
        await message.answer("❌ Phone number must be between 5 and 20 characters. Try again:")
        return

    session = get_session()
    try:
        if get_account_by_phone(session, phone_number):
            await message.answer(
                "❌ An account with this phone number already exists. Try a different number:"
            )
            return
    finally:
        session.close()

    await state.update_data(phone_number=phone_number)
    await state.set_state(AccountCreation.waiting_for_session_name)
    await message.answer(
        f"✅ Phone: {phone_number}\n\n"
        "What should be the session name?\n"
        "(This is used internally. e.g., 'session_1', 'main')"
    )


@router.message(AccountCreation.waiting_for_session_name)
async def process_session_name(message: Message, state: FSMContext):
    """Process session name input."""
    session_name = message.text.strip().replace(" ", "_").lower()

    if not session_name or len(session_name) < 2:
        await message.answer("❌ Session name must be at least 2 characters long. Try again:")
        return

    if len(session_name) > 30:
        await message.answer("❌ Session name must be 30 characters or less. Try again:")
        return

    if not session_name.replace("_", "").isalnum():
        await message.answer("❌ Session name can only contain letters, numbers, and underscores. Try again:")
        return

    data = await state.get_data()
    display_name = data["display_name"]
    phone_number = data["phone_number"]

    text = (
        "📋 Confirm Account Details\n\n"
        f"Display Name: {display_name}\n"
        f"Phone Number: {phone_number}\n"
        f"Session Name: {session_name}\n\n"
        "Is this correct?"
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
            f"✅ Account Created!\n\n"
            f"📊 {account.display_name}\n"
            f"📱 {account.phone_number}\n"
            f"🔥 Status: Warming\n\n"
            f"The account is ready for setup. "
            f"You can now add chats and assign templates to it.",
            reply_markup=get_accounts_menu(),
        )
    except Exception as e:
        logger.error(f"Error creating account: {e}", exc_info=True)
        await query.message.edit_text(
            f"❌ Error creating account: {str(e)}",
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
            await query.answer("✅ Account paused")
            await callback_account_detail(query)
        else:
            await query.answer("❌ Failed to pause account", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_resume_"))
async def callback_resume_account(query: CallbackQuery):
    """Resume a paused account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "active"):
            await query.answer("✅ Account resumed")
            await callback_account_detail(query)
        else:
            await query.answer("❌ Failed to resume account", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_activate_"))
async def callback_activate_account(query: CallbackQuery):
    """Activate an account from warming state."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "active"):
            await query.answer("✅ Account activated")
            await callback_account_detail(query)
        else:
            await query.answer("❌ Failed to activate account", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_warming_"))
async def callback_warming_account(query: CallbackQuery):
    """Set account to warming state."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_account_status(session, account_id, "warming"):
            await query.answer("✅ Account set to warming")
            await callback_account_detail(query)
        else:
            await query.answer("❌ Failed to set account to warming", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("account_disable_"))
async def callback_disable_account(query: CallbackQuery):
    """Disable an account."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if disable_account(session, account_id):
            await query.answer("✅ Account disabled")
            await callback_account_detail(query)
        else:
            await query.answer("❌ Failed to disable account", show_alert=True)
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
            await query.answer("❌ Account not found", show_alert=True)
            return

        chats = account.chats
        if not chats:
            text = f"💬 Chats for {account.display_name}\n\nNo chats assigned yet."
        else:
            text = f"💬 Chats for {account.display_name}\n\n"
            for chat in chats:
                status_emoji = {"active": "🟢", "paused": "⏸️", "error": "⚠️"}.get(chat.status, "❓")
                text += f"{status_emoji} {chat.title}\n"
                text += f"   Cooldown: {chat.cooldown_minutes}m\n"
                if chat.last_error:
                    text += f"   ⚠️ Error: {chat.last_error[:50]}\n"
                text += "\n"

        await query.message.edit_text(text, reply_markup=get_back_button())
    finally:
        session.close()
    await query.answer()
