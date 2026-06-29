from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_campaigns_menu(scheduler_running: bool = False) -> InlineKeyboardMarkup:
    """Campaigns/scheduler management menu."""
    buttons = []

    if scheduler_running:
        buttons.append([InlineKeyboardButton(text="⏸️ Stop Scheduler", callback_data="scheduler_stop")])
        buttons.append([InlineKeyboardButton(text="✅ Scheduler is RUNNING", callback_data="scheduler_status")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Start Scheduler", callback_data="scheduler_start")])
        buttons.append([InlineKeyboardButton(text="⏹️ Scheduler is STOPPED", callback_data="scheduler_status")])

    buttons.append([InlineKeyboardButton(text="🟢 Active Chats", callback_data="campaigns_active")])
    buttons.append([InlineKeyboardButton(text="⏱️ Next Scheduled", callback_data="campaigns_next")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
