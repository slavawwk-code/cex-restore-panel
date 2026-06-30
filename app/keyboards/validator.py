from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_validator_menu() -> InlineKeyboardMarkup:
    """Validator main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Проверить кампанию", callback_data="validator_validate")],
            [InlineKeyboardButton(text="Следующая отправка", callback_data="simulator_next")],
            [InlineKeyboardButton(text="Симуляция кампании", callback_data="simulator_full")],
            [InlineKeyboardButton(text="💪 Проверка системы", callback_data="validator_health")],
            [InlineKeyboardButton(text="📅 Предпросмотр расписания", callback_data="simulator_schedule")],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )


def get_validator_back_keyboard() -> InlineKeyboardMarkup:
    """Back button for validator."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="validator_menu")],
        ]
    )
