from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_templates_menu() -> InlineKeyboardMarkup:
    """Templates management menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Create Template", callback_data="template_create")],
            [InlineKeyboardButton(text="📋 View Templates", callback_data="templates_view")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")],
        ]
    )


def get_templates_list_keyboard(templates: list) -> InlineKeyboardMarkup:
    """Keyboard for listing templates."""
    buttons = []
    for template in templates:
        btn_text = f"📝 {template.name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"template_detail_{template.id}")])

    buttons.append([InlineKeyboardButton(text="➕ Create New Template", callback_data="template_create")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="templates_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_template_detail_keyboard(template_id: int, is_active: bool = True) -> InlineKeyboardMarkup:
    """Keyboard for template detail view."""
    buttons = [
        [InlineKeyboardButton(text="✏️ Edit Name", callback_data=f"template_edit_name_{template_id}")],
        [InlineKeyboardButton(text="✏️ Edit Text", callback_data=f"template_edit_text_{template_id}")],
    ]

    if is_active:
        buttons.append([InlineKeyboardButton(text="🚫 Disable Template", callback_data=f"template_disable_{template_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="✅ Enable Template", callback_data=f"template_enable_{template_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="templates_view")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_template_creation_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for template creation flow (cancel button)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="templates_list")],
        ]
    )


def get_template_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for confirming template creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm", callback_data="template_confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="templates_list")],
        ]
    )


def get_template_edit_menu(template_id: int) -> InlineKeyboardMarkup:
    """Keyboard for choosing what to edit."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Edit Name", callback_data=f"template_edit_name_{template_id}")],
            [InlineKeyboardButton(text="✏️ Edit Text", callback_data=f"template_edit_text_{template_id}")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data=f"template_detail_{template_id}")],
        ]
    )


def get_template_edit_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for confirming template edit."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Save Changes", callback_data="template_save_changes")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="template_cancel_edit")],
        ]
    )
