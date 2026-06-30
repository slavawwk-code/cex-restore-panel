from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_dashboard_menu() -> InlineKeyboardMarkup:
    """Dashboard main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть dashboard", callback_data="dashboard_view")],
            [InlineKeyboardButton(text="Журнал", callback_data="logs_menu")],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )


def get_dashboard_view_keyboard(accounts: list | None = None) -> InlineKeyboardMarkup:
    """Dashboard view with controls."""
    buttons = [
        [InlineKeyboardButton(text="Обновить", callback_data="dashboard_refresh")],
        [InlineKeyboardButton(text="Журнал", callback_data="logs_menu")],
    ]
    for account in accounts or []:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=account.display_name,
                    callback_data=f"account_detail_{account.id}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="campaigns_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
