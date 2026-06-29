from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu() -> InlineKeyboardMarkup:
    """Main menu keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Accounts", callback_data="accounts_list")],
            [InlineKeyboardButton(text="💬 Chats", callback_data="chats_list")],
            [InlineKeyboardButton(text="📝 Templates", callback_data="templates_list")],
            [InlineKeyboardButton(text="📢 Campaigns", callback_data="campaigns_menu")],
            [InlineKeyboardButton(text="🧪 Validator", callback_data="campaigns_menu")],
            [InlineKeyboardButton(text="📋 Logs", callback_data="logs_menu")],
            [InlineKeyboardButton(text="👥 Operators", callback_data="operators_menu")],
            [InlineKeyboardButton(text="⚙️ Settings", callback_data="settings_menu")],
        ]
    )


def get_back_button() -> InlineKeyboardMarkup:
    """Back to main menu button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")],
        ]
    )
