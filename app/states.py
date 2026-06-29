from aiogram.fsm.state import State, StatesGroup


class AccountCreation(StatesGroup):
    """FSM states for account creation flow."""

    waiting_for_display_name = State()
    waiting_for_phone_number = State()
    waiting_for_session_name = State()
    confirmation = State()


class TemplateCreation(StatesGroup):
    """FSM states for template creation flow."""

    waiting_for_name = State()
    waiting_for_text = State()
    confirmation = State()


class TemplateEdit(StatesGroup):
    """FSM states for template editing flow."""

    choosing_field = State()
    editing_name = State()
    editing_text = State()
    confirmation = State()


class ChatCreation(StatesGroup):
    """FSM states for chat creation wizard."""

    selecting_account = State()
    selecting_template = State()
    entering_username = State()
    entering_title = State()
    entering_cooldown = State()
    confirmation = State()


class ChatEdit(StatesGroup):
    """FSM states for chat editing."""

    choosing_field = State()
    changing_account = State()
    changing_template = State()
    changing_cooldown = State()
    confirmation = State()


class TelethonAuth(StatesGroup):
    """FSM states for Telethon authentication flow."""

    confirming_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()
