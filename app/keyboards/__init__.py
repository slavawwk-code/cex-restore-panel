from app.keyboards.main import get_main_menu, get_back_button
from app.keyboards.accounts import (
    get_accounts_menu,
    get_accounts_list_keyboard,
    get_account_detail_keyboard,
    get_account_creation_keyboard,
    get_account_confirmation_keyboard,
)
from app.keyboards.templates import (
    get_templates_menu,
    get_templates_list_keyboard,
    get_template_detail_keyboard,
    get_template_creation_keyboard,
    get_template_confirmation_keyboard,
    get_template_edit_menu,
    get_template_edit_confirmation_keyboard,
)
from app.keyboards.chats import (
    get_chats_menu,
    get_chats_list_keyboard,
    get_accounts_selection_keyboard,
    get_templates_selection_keyboard,
    get_chat_creation_cancel_keyboard,
    get_chat_confirmation_keyboard,
    get_chat_detail_keyboard,
    get_accounts_selection_for_change,
    get_templates_selection_for_change,
    get_chat_cooldown_cancel_keyboard,
    get_chat_error_keyboard,
)
from app.keyboards.dashboard import (
    get_dashboard_menu,
    get_dashboard_view_keyboard,
)
from app.keyboards.campaigns import get_campaigns_menu
from app.keyboards.logs import (
    get_logs_menu as get_logs_menu_keyboard,
    get_accounts_selection_for_logs,
    get_chats_selection_for_logs,
    get_logs_back_keyboard,
)

__all__ = [
    "get_main_menu",
    "get_back_button",
    "get_accounts_menu",
    "get_accounts_list_keyboard",
    "get_account_detail_keyboard",
    "get_account_creation_keyboard",
    "get_account_confirmation_keyboard",
    "get_templates_menu",
    "get_templates_list_keyboard",
    "get_template_detail_keyboard",
    "get_template_creation_keyboard",
    "get_template_confirmation_keyboard",
    "get_template_edit_menu",
    "get_template_edit_confirmation_keyboard",
    "get_chats_menu",
    "get_chats_list_keyboard",
    "get_accounts_selection_keyboard",
    "get_templates_selection_keyboard",
    "get_chat_creation_cancel_keyboard",
    "get_chat_confirmation_keyboard",
    "get_chat_detail_keyboard",
    "get_accounts_selection_for_change",
    "get_templates_selection_for_change",
    "get_chat_cooldown_cancel_keyboard",
    "get_chat_error_keyboard",
    "get_dashboard_menu",
    "get_dashboard_view_keyboard",
    "get_campaigns_menu",
    "get_logs_menu_keyboard",
    "get_accounts_selection_for_logs",
    "get_chats_selection_for_logs",
    "get_logs_back_keyboard",
]
