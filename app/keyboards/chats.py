from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_chats_menu() -> InlineKeyboardMarkup:
    """Chats management menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить чат", callback_data="chat_create")],
            [InlineKeyboardButton(text="Список чатов", callback_data="chats_view")],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )


def get_chats_list_keyboard(chats: list) -> InlineKeyboardMarkup:
    """Keyboard for listing chats."""
    buttons = []
    for chat in chats:
        status_emoji = {"active": "🟢", "paused": "⏸️", "error": "⚠️"}.get(chat.status, "❓")
        btn_text = f"{status_emoji} {chat.title}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"chat_detail_{chat.id}")])

    buttons.append([InlineKeyboardButton(text="Добавить чат", callback_data="chat_create")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="chats_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_accounts_selection_keyboard(accounts: list) -> InlineKeyboardMarkup:
    """Keyboard for selecting an account during chat creation."""
    buttons = []
    for account in accounts:
        status_emoji = {"active": "🟢", "paused": "⏸️", "warming": "🔥"}.get(account.status, "❓")
        btn_text = f"{status_emoji} {account.display_name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"create_chat_account_{account.id}")])

    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="chats_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_templates_selection_keyboard(templates: list) -> InlineKeyboardMarkup:
    """Keyboard for selecting a template during chat creation."""
    buttons = []
    for template in templates:
        btn_text = f"📝 {template.name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"create_chat_template_{template.id}")])

    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="chats_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chat_creation_cancel_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for canceling chat creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="chats_list")],
        ]
    )


def get_chat_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for confirming chat creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data="chat_confirm_create")],
            [InlineKeyboardButton(text="Отмена", callback_data="chats_list")],
        ]
    )


def get_chat_detail_keyboard(chat_id: int, status: str) -> InlineKeyboardMarkup:
    """Keyboard for chat detail view."""
    buttons = []

    if status == "active":
        buttons.append([InlineKeyboardButton(text="Приостановить", callback_data=f"chat_pause_{chat_id}")])
    elif status == "paused":
        buttons.append([InlineKeyboardButton(text="Возобновить", callback_data=f"chat_resume_{chat_id}")])
    elif status == "error":
        buttons.append([InlineKeyboardButton(text="Показать ошибку", callback_data=f"chat_error_{chat_id}")])

    buttons.append([InlineKeyboardButton(text="Сменить аккаунт", callback_data=f"chat_change_account_{chat_id}")])
    buttons.append([InlineKeyboardButton(text="Сменить шаблон", callback_data=f"chat_change_template_{chat_id}")])
    buttons.append([InlineKeyboardButton(text="Изменить интервал", callback_data=f"chat_change_cooldown_{chat_id}")])
    buttons.append([InlineKeyboardButton(text="Отключить чат", callback_data=f"chat_disable_{chat_id}")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="chats_view")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_accounts_selection_for_change(accounts: list, chat_id: int) -> InlineKeyboardMarkup:
    """Keyboard for selecting an account to change."""
    buttons = []
    for account in accounts:
        status_emoji = {"active": "🟢", "paused": "⏸️", "warming": "🔥"}.get(account.status, "❓")
        btn_text = f"{status_emoji} {account.display_name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"chat_set_account_{chat_id}_{account.id}")])

    buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"chat_detail_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_templates_selection_for_change(templates: list, chat_id: int) -> InlineKeyboardMarkup:
    """Keyboard for selecting a template to change."""
    buttons = []
    for template in templates:
        btn_text = f"📝 {template.name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"chat_set_template_{chat_id}_{template.id}")])

    buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"chat_detail_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chat_cooldown_cancel_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Keyboard for canceling cooldown change."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=f"chat_detail_{chat_id}")],
        ]
    )


def get_chat_error_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Keyboard for viewing chat error."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data=f"chat_detail_{chat_id}")],
        ]
    )


def get_account_chats_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Actions for chats scoped to one advertising account."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить чат", callback_data=f"chat_create_for_account_{account_id}")],
            [InlineKeyboardButton(text="Назначить чаты", callback_data=f"chat_create_for_account_{account_id}")],
            [InlineKeyboardButton(text="Назад", callback_data=f"account_detail_{account_id}")],
        ]
    )
