from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_account_auth_buttons(account_id: int, session_connected: bool) -> list:
    """Get auth-related buttons for account detail."""
    buttons = []

    if session_connected:
        buttons.append([InlineKeyboardButton(text="✅ Check Session Status", callback_data=f"auth_check_status_{account_id}")])
        buttons.append([InlineKeyboardButton(text="🚫 Disconnect Session", callback_data=f"auth_disconnect_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🔗 Connect Telegram Session", callback_data=f"auth_connect_{account_id}")])

    return buttons


def get_auth_confirmation_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Confirmation for connecting session."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm & Send Code", callback_data=f"auth_send_code_{account_id}")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"account_detail_{account_id}")],
        ]
    )


def get_code_input_cancel_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Cancel button for code input."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"account_detail_{account_id}")],
        ]
    )


def get_disconnect_confirmation_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Confirmation for disconnecting session."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Disconnect & Delete Session", callback_data=f"auth_confirm_disconnect_{account_id}")],
            [InlineKeyboardButton(text="⬅️ Cancel", callback_data=f"account_detail_{account_id}")],
        ]
    )
