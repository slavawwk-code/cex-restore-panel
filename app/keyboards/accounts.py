from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_accounts_menu() -> InlineKeyboardMarkup:
    """Accounts management menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить аккаунт", callback_data="account_add")],
            [InlineKeyboardButton(text="Список аккаунтов", callback_data="accounts_view")],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )


def get_accounts_list_keyboard(
    accounts: list, health_scores: dict[int, int] | None = None
) -> InlineKeyboardMarkup:
    """Keyboard for listing accounts."""
    buttons = []
    for account in accounts:
        score = (health_scores or {}).get(account.id)
        indicator = "🟢" if score is not None and score >= 90 else "🟡" if score is not None and score >= 60 else "🔴"
        btn_text = f"{indicator} {account.display_name} · {score}%" if score is not None else account.display_name
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"account_detail_{account.id}")])

    buttons.append([InlineKeyboardButton(text="Добавить аккаунт", callback_data="account_add")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="accounts_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_account_detail_keyboard(account_id: int, status: str, session_connected: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for account detail view."""
    telegram_callback = f"auth_methods_{account_id}"
    buttons = [
        [
            InlineKeyboardButton(text="Telegram", callback_data=telegram_callback),
            InlineKeyboardButton(text="Прокси", callback_data=f"proxy_menu_{account_id}"),
        ],
        [
            InlineKeyboardButton(text="Чаты", callback_data=f"account_chats_{account_id}"),
            InlineKeyboardButton(text="Health", callback_data=f"account_health_{account_id}"),
        ],
        [InlineKeyboardButton(text="Профиль устройства", callback_data=f"account_identity_{account_id}")],
        [InlineKeyboardButton(text="Настройки", callback_data=f"account_settings_{account_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="accounts_view")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_account_settings_keyboard(
    account_id: int, status: str, session_connected: bool
) -> InlineKeyboardMarkup:
    """Account state controls ordered as primary, secondary, danger, back."""
    buttons = []
    if status in {"paused", "warming"}:
        buttons.append(
            [InlineKeyboardButton(text="Активировать", callback_data=f"account_activate_{account_id}")]
        )
    elif status == "active":
        buttons.append(
            [InlineKeyboardButton(text="Приостановить", callback_data=f"account_pause_{account_id}")]
        )
    if status != "warming":
        buttons.append(
            [InlineKeyboardButton(text="Перевести на прогрев", callback_data=f"account_warming_{account_id}")]
        )
    if session_connected:
        buttons.append(
            [InlineKeyboardButton(text="Отключить Telegram", callback_data=f"auth_disconnect_{account_id}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="Тестовая отправка сейчас", callback_data=f"account_campaign_test_{account_id}")]
    )
    if status != "disabled":
        buttons.append(
            [InlineKeyboardButton(text="Отключить аккаунт", callback_data=f"account_disable_{account_id}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="Повторная авторизация", callback_data=f"lifecycle_reauth_prompt_{account_id}")]
    )
    buttons.append(
        [InlineKeyboardButton(text="Удалить аккаунт", callback_data=f"lifecycle_delete_prompt_{account_id}")]
    )
    buttons.append(
        [InlineKeyboardButton(text="Назад", callback_data=f"account_detail_{account_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_account_subpage_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data=f"account_detail_{account_id}")]
        ]
    )


def get_account_identity_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сменить профиль устройства",
                    callback_data=f"account_identity_regen_{account_id}",
                )
            ],
            [InlineKeyboardButton(text="Назад", callback_data=f"account_detail_{account_id}")],
        ]
    )


def get_account_identity_confirm_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить регенерацию",
                    callback_data=f"account_identity_confirm_{account_id}",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data=f"account_identity_{account_id}")],
        ]
    )


def get_account_creation_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for account creation flow (cancel button)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="accounts_list")],
        ]
    )


def get_account_confirmation_keyboard(account_id: int = None) -> InlineKeyboardMarkup:
    """Keyboard for confirming account creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data=f"account_confirm_{account_id or 'new'}")],
            [InlineKeyboardButton(text="Отмена", callback_data="accounts_list")],
        ]
    )
