import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.states import TelethonAuth
from app.keyboards.telethon_auth import (
    get_auth_confirmation_keyboard,
    get_code_input_cancel_keyboard,
    get_disconnect_confirmation_keyboard,
)
from app.database import get_session
from app.database.models import AdvertisingAccount
from app.services.telethon_auth import (
    send_login_code,
    sign_in_with_code,
    sign_in_with_password,
    check_session_status,
    disconnect_session,
    get_session_info,
    TelethonAuthError,
)
from telethon.errors import SessionPasswordNeededError

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("auth_connect_"))
async def callback_auth_connect(query: CallbackQuery, state: FSMContext):
    """Start authentication flow."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
        if not account:
            await query.answer("❌ Account not found", show_alert=True)
            return

        if not account.phone_number:
            await query.message.edit_text(
                "❌ No phone number configured for this account.\n\n"
                "Please set the phone number first.",
            )
            await query.answer()
            return

        await state.set_state(TelethonAuth.confirming_phone)
        await state.update_data(account_id=account_id, phone_number=account.phone_number)

        await query.message.edit_text(
            f"🔗 Connect Telegram Session\n\n"
            f"Phone: {account.phone_number}\n\n"
            f"A login code will be sent to your Telegram app.\n"
            f"Make sure you have access to it.",
            reply_markup=get_auth_confirmation_keyboard(account_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("auth_send_code_"))
async def callback_auth_send_code(query: CallbackQuery, state: FSMContext):
    """Send login code."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
        if not account:
            await query.answer("❌ Account not found", show_alert=True)
            return

        await query.message.edit_text("⏳ Sending login code to Telegram...")

        try:
            phone_code_hash = await send_login_code(account)
            await state.update_data(phone_code_hash=phone_code_hash)
            await state.set_state(TelethonAuth.waiting_for_code)

            await query.message.edit_text(
                "✅ Code sent to your Telegram app!\n\n"
                "Enter the 5-digit code below:\n"
                "(Check your Telegram account for the code)",
                reply_markup=get_code_input_cancel_keyboard(account_id),
            )
        except TelethonAuthError as e:
            await query.message.edit_text(
                f"❌ Failed to send code\n\n{str(e)}\n\n"
                f"Please check your phone number and try again.",
            )
            await state.clear()
    finally:
        session.close()
    await query.answer()


@router.message(TelethonAuth.waiting_for_code)
async def process_login_code(message: Message, state: FSMContext):
    """Process login code input."""
    code = message.text.strip()

    if not code or len(code) < 4:
        await message.answer("❌ Invalid code format. Please enter the 5-digit code:")
        return

    data = await state.get_data()
    account_id = data["account_id"]
    phone_code_hash = data["phone_code_hash"]

    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
        if not account:
            await message.answer("❌ Account not found")
            await state.clear()
            return

        await message.answer("⏳ Verifying code...")

        try:
            await sign_in_with_code(account, code, phone_code_hash)

            # Success - update database
            account.session_connected = True
            account.session_connected_at = None  # Will be set on first status check
            account.last_error = None
            session.commit()

            await state.clear()
            await message.answer(
                "✅ Session connected successfully!\n\n"
                "Your Telegram account is now linked to this advertising account."
            )
            logger.info(f"Account {account_id} authenticated successfully")

        except SessionPasswordNeededError:
            # 2FA required
            await state.set_state(TelethonAuth.waiting_for_password)
            await message.answer(
                "🔐 Two-Factor Authentication Required\n\n"
                "Enter your 2FA password:"
            )

        except TelethonAuthError as e:
            await message.answer(f"❌ {str(e)}\n\nPlease try again.")

    finally:
        session.close()


@router.message(TelethonAuth.waiting_for_password)
async def process_2fa_password(message: Message, state: FSMContext):
    """Process 2FA password input."""
    password = message.text.strip()

    if not password:
        await message.answer("❌ Password cannot be empty:")
        return

    data = await state.get_data()
    account_id = data["account_id"]

    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
        if not account:
            await message.answer("❌ Account not found")
            await state.clear()
            return

        await message.answer("⏳ Verifying password...")

        try:
            await sign_in_with_password(account, password)

            # Success - update database
            account.session_connected = True
            account.session_connected_at = None
            account.last_error = None
            session.commit()

            await state.clear()
            await message.answer(
                "✅ Two-Factor Authentication successful!\n\n"
                "Your Telegram account is now linked."
            )
            logger.info(f"Account {account_id} 2FA authenticated successfully")

        except TelethonAuthError as e:
            await message.answer(f"❌ {str(e)}\n\nPlease try again.")

    finally:
        session.close()


@router.callback_query(F.data.startswith("auth_check_status_"))
async def callback_auth_check_status(query: CallbackQuery):
    """Check session status."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
        if not account:
            await query.answer("❌ Account not found", show_alert=True)
            return

        await query.message.edit_text("⏳ Checking session status...")

        status = await check_session_status(session, account)

        if status["connected"]:
            text = (
                f"✅ Session Connected\n\n"
                f"📱 Telegram User: {status.get('username') or status.get('user_id')}\n"
                f"🆔 User ID: {status.get('user_id')}\n"
                f"✅ Status: Active"
            )
        else:
            text = (
                f"❌ Session Not Connected\n\n"
                f"Reason: {status.get('reason', 'Unknown')}\n\n"
                f"Please reconnect or check the session."
            )

        from app.handlers.accounts import callback_account_detail

        query.data = f"account_detail_{account_id}"
        # Show updated detail view
        await callback_account_detail(query)

    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("auth_disconnect_"))
async def callback_auth_disconnect(query: CallbackQuery):
    """Confirm disconnect."""
    account_id = int(query.data.split("_")[-1])

    await query.message.edit_text(
        "⚠️ Disconnect Session?\n\n"
        "This will disconnect your Telegram account.\n"
        "You can reconnect anytime.",
        reply_markup=get_disconnect_confirmation_keyboard(account_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("auth_confirm_disconnect_"))
async def callback_auth_confirm_disconnect(query: CallbackQuery):
    """Confirm and disconnect."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
        if not account:
            await query.answer("❌ Account not found", show_alert=True)
            return

        await query.message.edit_text("⏳ Disconnecting...")

        success = await disconnect_session(session, account, delete_file=True)

        if success:
            await query.answer("✅ Session disconnected")
            # Reload account detail
            from app.handlers.accounts import callback_account_detail

            query.data = f"account_detail_{account_id}"
            await callback_account_detail(query)
        else:
            await query.message.edit_text("❌ Failed to disconnect session")

    finally:
        session.close()
