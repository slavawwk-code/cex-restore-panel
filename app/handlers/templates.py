import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.states import TemplateCreation, TemplateEdit
from app.keyboards.templates import (
    get_templates_menu,
    get_templates_list_keyboard,
    get_template_detail_keyboard,
    get_template_creation_keyboard,
    get_template_confirmation_keyboard,
    get_template_edit_confirmation_keyboard,
)
from app.database import get_session
from app.services.templates import (
    create_template,
    list_templates,
    get_template,
    get_template_by_name,
    template_name_exists,
    update_template_name,
    update_template_text,
    disable_template,
    enable_template,
    get_template_preview,
)

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "templates_list")
async def callback_templates_menu(query: CallbackQuery):
    """Handle templates menu callback."""
    await query.message.edit_text(
        "📝 Управление шаблонами\n\nВыберите действие:",
        reply_markup=get_templates_menu(),
    )
    await query.answer()


@router.callback_query(F.data == "templates_view")
async def callback_view_templates(query: CallbackQuery):
    """View all message templates."""
    session = get_session()
    try:
        templates = list_templates(session, include_inactive=False)

        if not templates:
            await query.message.edit_text(
                "📝 Шаблоны\n\nШаблонов пока нет.\n\nСоздайте первый шаблон.",
                reply_markup=get_templates_menu(),
            )
            await query.answer()
            return

        text = "📝 Шаблоны\n\n"
        for template in templates:
            preview = get_template_preview(template.text, max_length=50)
            text += f"📝 {template.name}\n"
            text += f"   {preview}\n"
            text += f"   📅 {template.created_at.strftime('%d.%m.%Y')}\n\n"

        await query.message.edit_text(text, reply_markup=get_templates_list_keyboard(templates))
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data.startswith("template_detail_"))
async def callback_template_detail(query: CallbackQuery):
    """Show template detail."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        template = get_template(session, template_id)

        if not template:
            await query.answer("❌ Шаблон не найден", show_alert=True)
            return

        text = "📝 Карточка шаблона\n\n"
        text += f"Название: {template.name}\n\n"
        text += f"Текст:\n{template.text}\n\n"
        text += f"📅 Создан: {template.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"📝 Изменён: {template.updated_at.strftime('%d.%m.%Y %H:%M')}\n"

        if not template.is_active:
            text += "\n⚠️ Шаблон отключён"

        await query.message.edit_text(
            text,
            reply_markup=get_template_detail_keyboard(template_id, template.is_active),
        )
    finally:
        session.close()
    await query.answer()


@router.callback_query(F.data == "template_create")
async def callback_create_template_start(query: CallbackQuery, state: FSMContext):
    """Start template creation flow."""
    await state.set_state(TemplateCreation.waiting_for_name)
    await query.message.edit_text(
        "📝 Новый шаблон\n\n"
        "Введите уникальное название шаблона (2–64 символа):",
        reply_markup=get_template_creation_keyboard(),
    )
    await query.answer()


@router.message(TemplateCreation.waiting_for_name)
async def process_template_name(message: Message, state: FSMContext):
    """Process template name input."""
    name = message.text.strip()

    if not name or len(name) < 2:
        await message.answer("❌ Название должно содержать минимум 2 символа:")
        return

    if len(name) > 64:
        await message.answer("❌ Название не должно превышать 64 символа:")
        return

    session = get_session()
    try:
        if get_template_by_name(session, name):
            await message.answer(
                "❌ Шаблон с таким названием уже существует. Введите другое:"
            )
            return
    finally:
        session.close()

    await state.update_data(name=name)
    await state.set_state(TemplateCreation.waiting_for_text)
    await message.answer(
        f"✅ Название: {name}\n\n"
        "Введите текст шаблона (5–4096 символов):"
    )


@router.message(TemplateCreation.waiting_for_text)
async def process_template_text(message: Message, state: FSMContext):
    """Process template text input."""
    text = message.text.strip()

    if not text or len(text) < 5:
        await message.answer("❌ Текст должен содержать минимум 5 символов:")
        return

    if len(text) > 4096:
        await message.answer("❌ Текст не должен превышать 4096 символов:")
        return

    data = await state.get_data()
    name = data["name"]

    text_preview = get_template_preview(text, max_length=80)

    confirmation_text = (
        "📋 Проверьте шаблон\n\n"
        f"Название: {name}\n\n"
        f"Текст:\n{text_preview}\n\n"
        "Всё верно?"
    )

    await state.update_data(text=text)
    await state.set_state(TemplateCreation.confirmation)
    await message.answer(confirmation_text, reply_markup=get_template_confirmation_keyboard())


@router.callback_query(TemplateCreation.confirmation, F.data == "template_confirm")
async def confirm_template_creation(query: CallbackQuery, state: FSMContext):
    """Confirm and create the template."""
    data = await state.get_data()
    session = get_session()

    try:
        template = create_template(
            session,
            name=data["name"],
            text=data["text"],
        )

        await state.clear()
        await query.message.edit_text(
            f"✅ Шаблон создан\n\n"
            f"📝 {template.name}\n"
            "✅ Готов к использованию\n\n"
            "Теперь шаблон можно назначить чатам.",
            reply_markup=get_templates_menu(),
        )
    except Exception as e:
        logger.error(f"Error creating template: {e}", exc_info=True)
        await query.message.edit_text(
            "❌ Не удалось создать шаблон.",
            reply_markup=get_templates_menu(),
        )
    finally:
        session.close()

    await query.answer()


@router.callback_query(F.data.startswith("template_edit_name_"))
async def callback_edit_template_name_start(query: CallbackQuery, state: FSMContext):
    """Start editing template name."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        template = get_template(session, template_id)
        if not template:
            await query.answer("❌ Шаблон не найден", show_alert=True)
            return

        await state.set_state(TemplateEdit.editing_name)
        await state.update_data(template_id=template_id, old_name=template.name)
        await query.message.edit_text(
            "📝 Изменение названия\n\n"
            f"Текущее название: {template.name}\n\n"
            "Введите новое название (2–64 символа):",
            reply_markup=get_template_creation_keyboard(),
        )
    finally:
        session.close()
    await query.answer()


@router.message(TemplateEdit.editing_name)
async def process_new_template_name(message: Message, state: FSMContext):
    """Process new template name."""
    new_name = message.text.strip()

    if not new_name or len(new_name) < 2:
        await message.answer("❌ Название должно содержать минимум 2 символа:")
        return

    if len(new_name) > 64:
        await message.answer("❌ Название не должно превышать 64 символа:")
        return

    data = await state.get_data()
    old_name = data["old_name"]

    if new_name == old_name:
        await message.answer("⚠️ Новое название совпадает с текущим. Введите другое:")
        return

    session = get_session()
    try:
        if template_name_exists(session, new_name, exclude_id=data["template_id"]):
            await message.answer(
                "❌ Шаблон с таким названием уже существует. Введите другое:"
            )
            return
    finally:
        session.close()

    confirmation_text = (
        "📝 Подтвердите изменение\n\n"
        f"Старое название: {old_name}\n"
        f"Новое название: {new_name}\n\n"
        "Сохранить?"
    )

    await state.update_data(new_name=new_name)
    await state.set_state(TemplateEdit.confirmation)
    await message.answer(confirmation_text, reply_markup=get_template_edit_confirmation_keyboard())


@router.callback_query(F.data.startswith("template_edit_text_"))
async def callback_edit_template_text_start(query: CallbackQuery, state: FSMContext):
    """Start editing template text."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        template = get_template(session, template_id)
        if not template:
            await query.answer("❌ Шаблон не найден", show_alert=True)
            return

        await state.set_state(TemplateEdit.editing_text)
        await state.update_data(template_id=template_id, old_text=template.text)
        await query.message.edit_text(
            "📝 Изменение текста\n\n"
            f"Текущий текст:\n{template.text}\n\n"
            "Введите новый текст (5–4096 символов):",
            reply_markup=get_template_creation_keyboard(),
        )
    finally:
        session.close()
    await query.answer()


@router.message(TemplateEdit.editing_text)
async def process_new_template_text(message: Message, state: FSMContext):
    """Process new template text."""
    new_text = message.text.strip()

    if not new_text or len(new_text) < 5:
        await message.answer("❌ Текст должен содержать минимум 5 символов:")
        return

    if len(new_text) > 4096:
        await message.answer("❌ Текст не должен превышать 4096 символов:")
        return

    data = await state.get_data()
    old_text = data["old_text"]

    if new_text == old_text:
        await message.answer("⚠️ Новый текст совпадает с текущим. Введите другой:")
        return

    text_preview = get_template_preview(new_text, max_length=80)

    confirmation_text = (
        "📝 Подтвердите изменение\n\n"
        f"Новый текст:\n{text_preview}\n\n"
        "Сохранить?"
    )

    await state.update_data(new_text=new_text)
    await state.set_state(TemplateEdit.confirmation)
    await message.answer(confirmation_text, reply_markup=get_template_edit_confirmation_keyboard())


@router.callback_query(TemplateEdit.confirmation, F.data == "template_save_changes")
async def confirm_template_edit(query: CallbackQuery, state: FSMContext):
    """Confirm and save template edits."""
    data = await state.get_data()
    template_id = data["template_id"]
    session = get_session()

    try:
        if "new_name" in data:
            if not update_template_name(session, template_id, data["new_name"]):
                await query.answer("❌ Не удалось изменить название", show_alert=True)
                return

        if "new_text" in data:
            if not update_template_text(session, template_id, data["new_text"]):
                await query.answer("❌ Не удалось изменить текст", show_alert=True)
                return

        await state.clear()
        await query.answer("✅ Шаблон обновлён")

        query.data = f"template_detail_{template_id}"
        await callback_template_detail(query)

    except Exception as e:
        logger.error(f"Error updating template: {e}", exc_info=True)
        await query.answer("❌ Не удалось обновить шаблон", show_alert=True)
    finally:
        session.close()


@router.callback_query(TemplateEdit.confirmation, F.data == "template_cancel_edit")
async def cancel_template_edit(query: CallbackQuery, state: FSMContext):
    """Cancel template edit."""
    data = await state.get_data()
    template_id = data["template_id"]
    await state.clear()

    query.data = f"template_detail_{template_id}"
    await callback_template_detail(query)


@router.callback_query(F.data.startswith("template_disable_"))
async def callback_disable_template(query: CallbackQuery):
    """Disable a template."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if disable_template(session, template_id):
            await query.answer("✅ Шаблон отключён")
            await callback_template_detail(query)
        else:
            await query.answer("❌ Не удалось отключить шаблон", show_alert=True)
    finally:
        session.close()


@router.callback_query(F.data.startswith("template_enable_"))
async def callback_enable_template(query: CallbackQuery):
    """Enable a disabled template."""
    template_id = int(query.data.split("_")[-1])
    session = get_session()

    try:
        if enable_template(session, template_id):
            await query.answer("✅ Шаблон включён")
            await callback_template_detail(query)
        else:
            await query.answer("❌ Не удалось включить шаблон", show_alert=True)
    finally:
        session.close()


@router.callback_query(TemplateCreation.waiting_for_name, F.data == "templates_list")
@router.callback_query(TemplateCreation.waiting_for_text, F.data == "templates_list")
@router.callback_query(TemplateCreation.confirmation, F.data == "templates_list")
async def cancel_template_creation(query: CallbackQuery, state: FSMContext):
    """Cancel template creation."""
    await state.clear()
    await callback_templates_menu(query)
