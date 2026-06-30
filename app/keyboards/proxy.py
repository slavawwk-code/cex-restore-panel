from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_proxy_menu_keyboard(account_id: int, enabled: bool) -> InlineKeyboardMarkup:
    """Proxy controls for an advertising account."""
    buttons = []
    if enabled:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Быстрая проверка",
                    callback_data=f"proxy_fast_{account_id}",
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Полная диагностика",
                    callback_data=f"proxy_diagnostics_{account_id}",
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="История",
                    callback_data=f"proxy_history_{account_id}",
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Изменить",
                    callback_data=f"proxy_setup_{account_id}",
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Отключить",
                    callback_data=f"proxy_disable_{account_id}",
                )
            ]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Настроить прокси",
                    callback_data=f"proxy_setup_{account_id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=f"account_detail_{account_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_proxy_type_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Supported proxy protocol selector."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="SOCKS5", callback_data=f"proxy_type_{account_id}_SOCKS5"
                ),
                InlineKeyboardButton(
                    text="SOCKS4", callback_data=f"proxy_type_{account_id}_SOCKS4"
                ),
                InlineKeyboardButton(
                    text="HTTP", callback_data=f"proxy_type_{account_id}_HTTP"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_proxy_setup_method_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Choose between optimized paste mode and the manual wizard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Вставить строкой (рекомендуется)",
                    callback_data=f"proxy_paste_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Заполнить вручную",
                    callback_data=f"proxy_manual_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_proxy_skip_keyboard(account_id: int, field: str) -> InlineKeyboardMarkup:
    """Skip optional proxy credentials."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пропустить",
                    callback_data=f"proxy_skip_{field}_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_proxy_cancel_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Cancel proxy configuration."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"proxy_menu_{account_id}"
                )
            ]
        ]
    )


def get_proxy_confirmation_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Confirm proxy settings without exposing the password."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сохранить",
                    callback_data=f"proxy_save_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить", callback_data=f"proxy_setup_{account_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_proxy_detection_confirmation_keyboard(
    account_id: int,
) -> InlineKeyboardMarkup:
    """Confirm a pasted proxy and immediately detect its working type."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сохранить и проверить",
                    callback_data=f"proxy_save_test_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить", callback_data=f"proxy_setup_{account_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_proxy_saved_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Offer an immediate Telegram connectivity test after saving."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Проверить", callback_data=f"proxy_fast_{account_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Позже", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_full_diagnostics_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """Offer full diagnostics when a fast check has no saved type."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Полная диагностика",
                    callback_data=f"proxy_diagnostics_{account_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад", callback_data=f"proxy_menu_{account_id}"
                )
            ],
        ]
    )


def get_proxy_history_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data=f"proxy_menu_{account_id}")]
        ]
    )
