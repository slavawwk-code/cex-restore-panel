from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_accounts_menu() -> InlineKeyboardMarkup:
    """Accounts management menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Account", callback_data="account_add")],
            [InlineKeyboardButton(text="📋 View Accounts", callback_data="accounts_view")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")],
        ]
    )


def get_accounts_list_keyboard(accounts: list) -> InlineKeyboardMarkup:
    """Keyboard for listing accounts."""
    buttons = []
    for account in accounts:
        btn_text = f"{account.display_name} ({account.status})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"account_detail_{account.id}")])

    buttons.append([InlineKeyboardButton(text="➕ Add New Account", callback_data="account_add")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="accounts_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_account_detail_keyboard(account_id: int, status: str, session_connected: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for account detail view."""
    buttons = []

    if status == "active":
        buttons.append([InlineKeyboardButton(text="⏸️ Pause", callback_data=f"account_pause_{account_id}")])
    elif status == "paused":
        buttons.append([InlineKeyboardButton(text="▶️ Resume", callback_data=f"account_resume_{account_id}")])
    elif status == "warming":
        buttons.append([InlineKeyboardButton(text="✅ Activate", callback_data=f"account_activate_{account_id}")])

    # Telegram session buttons
    if session_connected:
        buttons.append([InlineKeyboardButton(text="✅ Check Session Status", callback_data=f"auth_check_status_{account_id}")])
        buttons.append([InlineKeyboardButton(text="🚫 Disconnect Session", callback_data=f"auth_disconnect_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🔗 Connect Telegram Session", callback_data=f"auth_connect_{account_id}")])

    buttons.append([InlineKeyboardButton(text="🔄 Set to Warming", callback_data=f"account_warming_{account_id}")])
    buttons.append([InlineKeyboardButton(text="💬 View Chats", callback_data=f"account_chats_{account_id}")])

    if status != "disabled":
        buttons.append([InlineKeyboardButton(text="🚫 Disable Account", callback_data=f"account_disable_{account_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="accounts_view")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_account_creation_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for account creation flow (cancel button)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="accounts_list")],
        ]
    )


def get_account_confirmation_keyboard(account_id: int = None) -> InlineKeyboardMarkup:
    """Keyboard for confirming account creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm", callback_data=f"account_confirm_{account_id or 'new'}")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="accounts_list")],
        ]
    )
