from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_validator_menu() -> InlineKeyboardMarkup:
    """Validator main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Validate Campaign", callback_data="validator_validate")],
            [InlineKeyboardButton(text="🧪 Simulate Next Send", callback_data="simulator_next")],
            [InlineKeyboardButton(text="📋 Simulate Full Campaign", callback_data="simulator_full")],
            [InlineKeyboardButton(text="💪 Health Check", callback_data="validator_health")],
            [InlineKeyboardButton(text="📅 Preview Schedule", callback_data="simulator_schedule")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")],
        ]
    )


def get_validator_back_keyboard() -> InlineKeyboardMarkup:
    """Back button for validator."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data="campaigns_menu")],
        ]
    )
