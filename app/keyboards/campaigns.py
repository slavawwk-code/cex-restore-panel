from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_campaigns_menu(scheduler_running: bool = False) -> InlineKeyboardMarkup:
    """Campaigns/scheduler management menu."""
    buttons = []

    if scheduler_running:
        buttons.append([InlineKeyboardButton(text="Остановить планировщик", callback_data="scheduler_stop")])
        buttons.append([InlineKeyboardButton(text="🟢 Планировщик запущен", callback_data="scheduler_status")])
    else:
        buttons.append([InlineKeyboardButton(text="Запустить планировщик", callback_data="scheduler_start")])
        buttons.append([InlineKeyboardButton(text="⚪ Планировщик остановлен", callback_data="scheduler_status")])

    buttons.append([InlineKeyboardButton(text="🟢 Активные чаты", callback_data="campaigns_active")])
    buttons.append([InlineKeyboardButton(text="Ближайшие отправки", callback_data="campaigns_next")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="main_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
