from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from app.keyboards.main import get_main_menu
from app.database import get_session
from app.database.models import User

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    session = get_session()
    try:
        user = session.query(User).filter(User.telegram_id == message.from_user.id).first()

        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                role="operator",
            )
            session.add(user)
            session.commit()

        await message.answer(
            "<b>Cex Restore Panel</b>\n\nВыберите раздел.",
            reply_markup=get_main_menu(),
            parse_mode="HTML",
        )
    finally:
        session.close()


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(query: CallbackQuery):
    """Back to main menu."""
    await query.message.edit_text(
        "<b>Cex Restore Panel</b>\n\nВыберите раздел.",
        reply_markup=get_main_menu(),
        parse_mode="HTML",
    )
    await query.answer()


@router.callback_query(F.data.in_({"operators_menu", "settings_menu"}))
async def callback_unavailable_section(query: CallbackQuery):
    """Explain unavailable menu sections instead of ignoring the callback."""
    section = "Операторы" if query.data == "operators_menu" else "Настройки"
    await query.message.edit_text(
        f"Раздел «{section}» пока не реализован.",
        reply_markup=get_main_menu(),
    )
    await query.answer()
