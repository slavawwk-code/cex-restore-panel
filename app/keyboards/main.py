from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu() -> InlineKeyboardMarkup:
    """Main menu keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Аккаунты", callback_data="accounts_list"),
                InlineKeyboardButton(text="Чаты", callback_data="chats_list"),
            ],
            [
                InlineKeyboardButton(text="Шаблоны", callback_data="templates_list"),
                InlineKeyboardButton(text="Кампании", callback_data="campaigns_menu"),
            ],
            [
                InlineKeyboardButton(text="Журнал", callback_data="logs_menu"),
                InlineKeyboardButton(text="Проверка", callback_data="validator_menu"),
            ],
            [
                InlineKeyboardButton(text="Операторы", callback_data="operators_menu"),
                InlineKeyboardButton(text="Настройки", callback_data="settings_menu"),
            ],
        ]
    )


def get_back_button() -> InlineKeyboardMarkup:
    """Back to main menu button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )
