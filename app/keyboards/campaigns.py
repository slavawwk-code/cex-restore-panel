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


def get_campaigns_list_keyboard(campaigns: list, scheduler_running: bool = False) -> InlineKeyboardMarkup:
    """List campaigns with edit entry points."""
    buttons = []
    for campaign in campaigns:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=campaign.name,
                    callback_data=f"campaign_detail_{campaign.id}",
                )
            ]
        )
    buttons.extend(get_campaigns_menu(scheduler_running).inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_campaign_detail_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Тестовая отправка сейчас", callback_data=f"campaign_send_now_{campaign_id}")],
            [InlineKeyboardButton(text="⚙️ Edit Campaign", callback_data=f"campaign_edit_{campaign_id}")],
            [InlineKeyboardButton(text="Назад", callback_data="campaigns_menu")],
        ]
    )


def get_campaign_edit_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Change template", callback_data=f"campaign_edit_template_{campaign_id}")],
            [InlineKeyboardButton(text="Change interval", callback_data=f"campaign_edit_interval_{campaign_id}")],
            [InlineKeyboardButton(text="Manage chats", callback_data=f"campaign_edit_chats_{campaign_id}")],
            [InlineKeyboardButton(text="Rename campaign", callback_data=f"campaign_edit_rename_{campaign_id}")],
            [InlineKeyboardButton(text="Configure schedule", callback_data=f"campaign_edit_schedule_{campaign_id}")],
            [InlineKeyboardButton(text="Тестовая отправка сейчас", callback_data=f"campaign_send_now_{campaign_id}")],
            [InlineKeyboardButton(text="Back", callback_data=f"campaign_detail_{campaign_id}")],
        ]
    )


def get_campaign_first_send_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить сейчас", callback_data=f"campaign_first_now_{campaign_id}")],
            [InlineKeyboardButton(text="Через 5 минут", callback_data=f"campaign_first_5min_{campaign_id}")],
            [InlineKeyboardButton(text="По обычному интервалу", callback_data=f"campaign_first_regular_{campaign_id}")],
            [InlineKeyboardButton(text="Назад", callback_data=f"campaign_edit_{campaign_id}")],
        ]
    )


def get_account_campaign_test_keyboard(campaigns: list, account_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=campaign.name,
                callback_data=f"campaign_send_now_{campaign.id}",
            )
        ]
        for campaign in campaigns
    ]
    buttons.append([InlineKeyboardButton(text="Назад", callback_data=f"account_settings_{account_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_campaign_template_keyboard(templates: list, campaign_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=template.name,
                callback_data=f"campaign_set_template_{campaign_id}_{template.id}",
            )
        ]
        for template in templates
    ]
    buttons.append([InlineKeyboardButton(text="Back", callback_data=f"campaign_edit_{campaign_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_campaign_chats_keyboard(chats: list, campaign_id: int, selected_ids: set[int]) -> InlineKeyboardMarkup:
    buttons = []
    for chat in chats:
        marker = "✓" if chat.id in selected_ids else " "
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {chat.title}",
                    callback_data=f"campaign_toggle_chat_{campaign_id}_{chat.id}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="Сохранить", callback_data=f"campaign_confirm_chats_{campaign_id}")])
    buttons.append([InlineKeyboardButton(text="Back", callback_data=f"campaign_edit_{campaign_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_campaign_destructive_confirmation_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data=f"campaign_save_chats_{campaign_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"campaign_edit_chats_{campaign_id}")],
        ]
    )


def get_campaign_schedule_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Задать окно времени", callback_data=f"campaign_schedule_window_{campaign_id}")],
            [InlineKeyboardButton(text="Включить весь день", callback_data=f"campaign_schedule_all_day_{campaign_id}")],
            [InlineKeyboardButton(text="Выключить расписание", callback_data=f"campaign_schedule_disable_{campaign_id}")],
            [InlineKeyboardButton(text="Back", callback_data=f"campaign_edit_{campaign_id}")],
        ]
    )
