from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_auth_methods_keyboard(
    account_id: int,
    session_connected: bool,
    has_session: bool,
) -> InlineKeyboardMarkup:
    """Session methods ordered by file import, phone login, and fallback string."""
    buttons = [
        [
            InlineKeyboardButton(
                text="Импорт .session",
                callback_data=f"auth_import_{account_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="Войти по номеру",
                callback_data=f"auth_connect_{account_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="Добавить StringSession",
                callback_data=f"auth_string_{account_id}",
            )
        ],
    ]
    if has_session:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Проверить сессию",
                    callback_data=f"auth_check_status_{account_id}",
                )
            ]
        )
    if session_connected or has_session:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Отключить сессию",
                    callback_data=f"auth_disconnect_{account_id}",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton(text="Назад", callback_data=f"account_detail_{account_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_auth_cancel_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=f"auth_methods_{account_id}")]
        ]
    )


def get_account_auth_buttons(account_id: int, session_connected: bool) -> list:
    """Get auth-related buttons for account detail."""
    buttons = []

    if session_connected:
        buttons.append([InlineKeyboardButton(text="Проверить сессию", callback_data=f"auth_check_status_{account_id}")])
        buttons.append([InlineKeyboardButton(text="Отключить сессию", callback_data=f"auth_disconnect_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="Подключить Telegram", callback_data=f"auth_connect_{account_id}")])

    return buttons


def get_auth_confirmation_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Confirmation for connecting session."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Запросить код", callback_data=f"auth_send_code_{account_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"account_detail_{account_id}")],
        ]
    )


def get_code_input_cancel_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Cancel button for code input."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="К аккаунту", callback_data=f"account_detail_{account_id}")],
        ]
    )


def get_disconnect_confirmation_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Confirmation for disconnecting session."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отключить и удалить сессию", callback_data=f"auth_confirm_disconnect_{account_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"account_detail_{account_id}")],
        ]
    )
