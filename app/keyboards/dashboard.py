from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_dashboard_menu() -> InlineKeyboardMarkup:
    """Dashboard main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 View Dashboard", callback_data="dashboard_view")],
            [InlineKeyboardButton(text="📋 Logs", callback_data="logs_menu")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")],
        ]
    )


def get_dashboard_view_keyboard() -> InlineKeyboardMarkup:
    """Dashboard view with controls."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="dashboard_refresh")],
            [InlineKeyboardButton(text="📋 Logs", callback_data="logs_menu")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="campaigns_menu")],
        ]
    )
