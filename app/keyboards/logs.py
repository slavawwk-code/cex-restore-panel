from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_logs_menu() -> InlineKeyboardMarkup:
    """Logs main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Последние события", callback_data="logs_recent")],
            [InlineKeyboardButton(text="Только ошибки", callback_data="logs_errors")],
            [InlineKeyboardButton(text="Только успешные", callback_data="logs_success")],
            [InlineKeyboardButton(text="📱 По аккаунту", callback_data="logs_by_account")],
            [InlineKeyboardButton(text="По чату", callback_data="logs_by_chat")],
            [InlineKeyboardButton(text="Назад", callback_data="campaigns_menu")],
        ]
    )


def get_accounts_selection_for_logs(accounts: list) -> InlineKeyboardMarkup:
    """Keyboard for selecting account in logs."""
    buttons = []
    for account in accounts:
        btn_text = f"📱 {account.display_name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"logs_account_{account.id}")])

    buttons.append([InlineKeyboardButton(text="Назад", callback_data="logs_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chats_selection_for_logs(chats: list) -> InlineKeyboardMarkup:
    """Keyboard for selecting chat in logs."""
    buttons = []
    for chat in chats:
        btn_text = f"💬 {chat.title}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"logs_chat_{chat.id}")])

    buttons.append([InlineKeyboardButton(text="Назад", callback_data="logs_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_logs_back_keyboard() -> InlineKeyboardMarkup:
    """Back button for logs."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="logs_menu")],
        ]
    )
