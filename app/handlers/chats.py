import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.states import ChatCreation, ChatEdit
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
from app.keyboards.main import get_back_button
from app.database import get_session
from app.database.models import Chat, AdvertisingAccount, Template
from app.services.chats import (
    create_chat,
    list_chats,
    get_chat,
    get_chat_info,
    update_chat_account,
    update_chat_template,
    update_chat_cooldown,
    update_chat_status,
    disable_chat,
    count_account_chats,
    get_status_emoji,
)
from app.services.accounts import list_accounts, get_account
from app.services.templates import list_templates

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "chats_list")
async def callback_chats_menu(query: CallbackQuery):
    """Handle chats menu callback."""
    await query.message.edit_text(
        "💬 Chats Management\n\nWhat would you like to do?",
        reply_markup=get_chats_menu(),
    )
    await query.answer()


@router.callback_query(F.data == "chats_view")
async def callback_view_chats(query: CallbackQuery):
    """View all chats."""
    session = get_session()
    try:
        chats = list_chats(session, include_inactive=False)

        if not chats:
            await query.message.edit_text(
                "💬 Chats\n\nNo chats yet.\n\nCreate one to get started.",
                reply_markup=get_chats_menu(),
            )
            await query.answer()
            return

        text = "💬 Chats\n\n"
        for chat in chats:
            emoji = get_status_emoji(chat.status)
            account_name = chat.account.display_name if chat.account else "Unknown"
            template_name = chat.template.name if chat.template else "None"

            text += f"{emoji} {chat.title}\n"
            text += f"   📱 {account_name} • 📝 {template_name}\n"
            text += f"   ⏱️ {chat.cooldown_minutes}m"

            if chat.last_sent_at:
                text += f" • 📅 {chat.last_sent_at.strftime('%Y-%m-%d %H:%M')}"
            else:
                text += f" • Never sent"
            text += "\n\n"

        await query.message.edit_text(text, reply_markup=get_chats_list_keyboard(chats))
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_detail_"))
async def callback_chat_detail(query: CallbackQuery):
    """Show chat detail."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        info = get_chat_info(session, chat_id)
        if not info:
            await query.answer("❌ Chat not found", show_alert=True)
            return

        emoji = get_status_emoji(info["status"])
        text = f"💬 Chat Details\n\n"
        text += f"{emoji} {info['title']}\n\n"
        text += f"Chat ID: {info['username_or_chat_id']}\n"
        text += f"📱 Account: {info['account_name']}\n"
        text += f"📝 Template: {info['template_name']}\n"
        text += f"⏱️ Cooldown: {info['cooldown_minutes']} minutes\n"
        text += f"📅 Created: {info['created_at'].strftime('%Y-%m-%d %H:%M')}\n"

        if info["last_sent_at"]:
            text += f"📤 Last sent: {info['last_sent_at'].strftime('%Y-%m-%d %H:%M')}\n"
        else:
            text += f"📤 Never sent\n"

        if info["last_error"]:
            text += f"\n⚠️ Error: {info['last_error'][:100]}\n"

        await query.message.edit_text(
            text,
            reply_markup=get_chat_detail_keyboard(chat_id, info["status"]),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "chat_create")
async def callback_create_chat_step1(query: CallbackQuery, state: FSMContext):
    """Start chat creation - step 1: select account."""
    session = get_session()
    try:
        accounts = list_accounts(session)
        active_accounts = [a for a in accounts if a.status == "active"]

        if not active_accounts:
            await query.message.edit_text(
                "❌ No active accounts available.\n\nCreate an account first.",
                reply_markup=get_chats_menu(),
            )
            await query.answer()
            return

        await state.set_state(ChatCreation.selecting_account)
        await query.message.edit_text(
            "💬 Create New Chat\n\n"
            "Step 1: Select Advertising Account\n\n"
            "Which account will handle this chat?",
            reply_markup=get_accounts_selection_keyboard(active_accounts),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(ChatCreation.selecting_account, F.data.startswith("create_chat_account_"))
async def callback_create_chat_step2(query: CallbackQuery, state: FSMContext):
    """Step 2: select template."""
    account_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        account = get_account(session, account_id)
        if not account:
            await query.answer("❌ Account not found", show_alert=True)
            return

        templates = list_templates(session, include_inactive=False)
        if not templates:
            await query.message.edit_text(
                "❌ No active templates available.\n\nCreate a template first.",
                reply_markup=get_chats_menu(),
            )
            await query.answer()
            return

        await state.update_data(account_id=account_id, account_name=account.display_name)
        await state.set_state(ChatCreation.selecting_template)
        await query.message.edit_text(
            "💬 Create New Chat\n\n"
            f"Step 2: Select Template\n\n"
            f"Account: {account.display_name}\n\n"
            "Which template will this chat use?",
            reply_markup=get_templates_selection_keyboard(templates),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(ChatCreation.selecting_template, F.data.startswith("create_chat_template_"))
async def callback_create_chat_step3(query: CallbackQuery, state: FSMContext):
    """Step 3: enter chat username or ID."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        template = session.query(Template).filter(Template.id == template_id).first()
        if not template:
            await query.answer("❌ Template not found", show_alert=True)
            return

        await state.update_data(template_id=template_id, template_name=template.name)
        await state.set_state(ChatCreation.entering_username)
        await query.message.edit_text(
            "💬 Create New Chat\n\n"
            "Step 3: Chat Username or ID\n\n"
            "Enter the chat username (e.g., @groupname) or chat ID (e.g., -100123456789)",
            reply_markup=get_chat_creation_cancel_keyboard(),
        )
    finally:
        session.close()
    await query.answer()


@router.message(ChatCreation.entering_username)
async def process_chat_username(message: Message, state: FSMContext):
    """Process chat username/ID input."""
    username = message.text.strip()

    if not username:
        await message.answer("❌ Username or chat ID cannot be empty. Try again:")
        return

    if len(username) < 3:
        await message.answer("❌ Invalid username or chat ID. Try again:")
        return

    if len(username) > 50:
        await message.answer("❌ Username or chat ID too long. Try again:")
        return

    if username.startswith("@"):
        if not re.match(r"^@[a-zA-Z0-9_]{3,32}$", username):
            await message.answer(
                "❌ Invalid username format. Use @username (letters, numbers, underscores only).\n\nTry again:"
            )
            return
    else:
        if not username.lstrip("-").isdigit():
            await message.answer(
                "❌ Invalid chat ID. Use either @username or negative number (e.g., -100123456789).\n\nTry again:"
            )
            return

    await state.update_data(username_or_chat_id=username)
    await state.set_state(ChatCreation.entering_title)
    await message.answer(
        f"✅ Chat: {username}\n\n"
        "Step 4: Chat Display Name\n\n"
        "What should be the display name for this chat?\n"
        "(2–100 characters, e.g., 'MEXC Recovery')"
    )


@router.message(ChatCreation.entering_title)
async def process_chat_title(message: Message, state: FSMContext):
    """Process chat display name input."""
    title = message.text.strip()

    if not title or len(title) < 2:
        await message.answer("❌ Display name must be at least 2 characters long. Try again:")
        return

    if len(title) > 100:
        await message.answer("❌ Display name must be 100 characters or less. Try again:")
        return

    await state.update_data(title=title)
    await state.set_state(ChatCreation.entering_cooldown)
    await message.answer(
        f"✅ Display name: {title}\n\n"
        "Step 5: Cooldown (minutes)\n\n"
        "How many minutes between messages?\n"
        "(1–1440 minutes)"
    )


@router.message(ChatCreation.entering_cooldown)
async def process_chat_cooldown(message: Message, state: FSMContext):
    """Process cooldown input."""
    try:
        cooldown = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Please enter a valid number. Try again:")
        return

    if cooldown < 1 or cooldown > 1440:
        await message.answer("❌ Cooldown must be between 1 and 1440 minutes. Try again:")
        return

    data = await state.get_data()
    account_name = data["account_name"]
    template_name = data["template_name"]
    title = data["title"]
    username = data["username_or_chat_id"]

    confirmation_text = (
        "📋 Confirm Chat Configuration\n\n"
        f"📱 Account: {account_name}\n"
        f"📝 Template: {template_name}\n"
        f"💬 Chat: {title}\n"
        f"ID: {username}\n"
        f"⏱️ Cooldown: {cooldown} minutes\n"
        f"🟢 Status: Active\n\n"
        "Is this correct?"
    )

    await state.update_data(cooldown=cooldown)
    await state.set_state(ChatCreation.confirmation)
    await message.answer(confirmation_text, reply_markup=get_chat_confirmation_keyboard())


@router.callback_query(ChatCreation.confirmation, F.data == "chat_confirm_create")
async def confirm_chat_creation(query: CallbackQuery, state: FSMContext):
    """Confirm and create the chat."""
    data = await state.get_data()
    session = get_session()

    try:
        chat = create_chat(
            session,
            advertising_account_id=data["account_id"],
            template_id=data["template_id"],
            title=data["title"],
            username_or_chat_id=data["username_or_chat_id"],
            cooldown_minutes=data["cooldown"],
        )

        await state.clear()
        await query.message.edit_text(
            f"✅ Chat Created!\n\n"
            f"💬 {chat.title}\n"
            f"📱 {data['account_name']}\n"
            f"📝 {data['template_name']}\n"
            f"⏱️ {data['cooldown']}m\n\n"
            f"The chat is ready and will receive messages on schedule.",
            reply_markup=get_chats_menu(),
        )
    except Exception as e:
        logger.error(f"Error creating chat: {e}", exc_info=True)
        await query.message.edit_text(
            f"❌ Error creating chat: {str(e)}",
            reply_markup=get_chats_menu(),
        )
    finally:
        session.close()

    await query.answer()


@router.callback_query(F.data.startswith("chat_pause_"))
async def callback_pause_chat(query: CallbackQuery):
    """Pause a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_chat_status(session, chat_id, "paused"):
            await query.answer("✅ Chat paused")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Failed to pause chat", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_resume_"))
async def callback_resume_chat(query: CallbackQuery):
    """Resume a paused chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if update_chat_status(session, chat_id, "active"):
            await query.answer("✅ Chat resumed")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Failed to resume chat", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_change_account_"))
async def callback_change_chat_account(query: CallbackQuery):
    """Change the account for a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        accounts = list_accounts(session)
        active_accounts = [a for a in accounts if a.status == "active"]

        if not active_accounts:
            await query.answer("❌ No active accounts available", show_alert=True)
            return

        await query.message.edit_text(
            "💬 Change Account\n\nSelect the new account:",
            reply_markup=get_accounts_selection_for_change(active_accounts, chat_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_set_account_"))
async def callback_set_chat_account(query: CallbackQuery):
    """Set the selected account."""
    parts = query.data.split("_")
    chat_id = int(parts[3])
    account_id = int(parts[4])
    session = get_session()

    try:
        if update_chat_account(session, chat_id, account_id):
            await query.answer("✅ Account changed")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Failed to change account", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_change_template_"))
async def callback_change_chat_template(query: CallbackQuery):
    """Change the template for a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        templates = list_templates(session, include_inactive=False)

        if not templates:
            await query.answer("❌ No active templates available", show_alert=True)
            return

        await query.message.edit_text(
            "💬 Change Template\n\nSelect the new template:",
            reply_markup=get_templates_selection_for_change(templates, chat_id),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_set_template_"))
async def callback_set_chat_template(query: CallbackQuery):
    """Set the selected template."""
    parts = query.data.split("_")
    chat_id = int(parts[3])
    template_id = int(parts[4])
    session = get_session()

    try:
        if update_chat_template(session, chat_id, template_id):
            await query.answer("✅ Template changed")
            await callback_chat_detail(query)
        else:
            await query.answer("❌ Failed to change template", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_change_cooldown_"))
async def callback_change_cooldown(query: CallbackQuery, state: FSMContext):
    """Start cooldown change."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        chat = get_chat(session, chat_id)
        if not chat:
            await query.answer("❌ Chat not found", show_alert=True)
            return

        await state.set_state(ChatEdit.changing_cooldown)
        await state.update_data(chat_id=chat_id)
        await query.message.edit_text(
            f"💬 Change Cooldown\n\n"
            f"Current cooldown: {chat.cooldown_minutes} minutes\n\n"
            f"Enter the new cooldown (1–1440 minutes):",
            reply_markup=get_chat_cooldown_cancel_keyboard(chat_id),
        )
    finally:
        session.close()
    await query.answer()


@router.message(ChatEdit.changing_cooldown)
async def process_new_cooldown(message: Message, state: FSMContext):
    """Process new cooldown input."""
    try:
        cooldown = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Please enter a valid number. Try again:")
        return

    if cooldown < 1 or cooldown > 1440:
        await message.answer("❌ Cooldown must be between 1 and 1440 minutes. Try again:")
        return

    data = await state.get_data()
    chat_id = data["chat_id"]
    session = get_session()

    try:
        if update_chat_cooldown(session, chat_id, cooldown):
            await state.clear()
            await message.answer("✅ Cooldown updated successfully")
            query_obj = type("obj", (object,), {"data": f"chat_detail_{chat_id}", "message": message})()
            await callback_chat_detail(query_obj)
        else:
            await message.answer("❌ Failed to update cooldown")
    finally:
        session.close()


@router.callback_query(F.data.startswith("chat_error_"))
async def callback_view_chat_error(query: CallbackQuery):
    """View chat error message."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        chat = get_chat(session, chat_id)
        if not chat:
            await query.answer("❌ Chat not found", show_alert=True)
            return

        if not chat.last_error:
            await query.message.edit_text(
                "❌ No error recorded for this chat.",
                reply_markup=get_chat_error_keyboard(chat_id),
            )
        else:
            await query.message.edit_text(
                f"⚠️ Last Error\n\n{chat.last_error}",
                reply_markup=get_chat_error_keyboard(chat_id),
            )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("chat_disable_"))
async def callback_disable_chat(query: CallbackQuery):
    """Disable a chat."""
    chat_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if disable_chat(session, chat_id):
            await query.answer("✅ Chat disabled")
            await callback_view_chats(query)
        else:
            await query.answer("❌ Failed to disable chat", show_alert=True)
    finally:
        session.close()


@router.callback_query(ChatCreation.waiting_for_username, F.data == "chats_list")
@router.callback_query(ChatCreation.waiting_for_title, F.data == "chats_list")
@router.callback_query(ChatCreation.waiting_for_cooldown, F.data == "chats_list")
@router.callback_query(ChatCreation.confirmation, F.data == "chats_list")
async def cancel_chat_creation(query: CallbackQuery, state: FSMContext):
    """Cancel chat creation."""
    await state.clear()
    await callback_chats_menu(query)
