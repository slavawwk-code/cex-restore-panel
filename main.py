import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Dispatcher, Bot
from aiogram.types import BotCommand
from app.database import init_db
from app.handlers import start_router, accounts_router, templates_router, chats_router, dashboard_router, logs_router, telethon_auth_router
from app.handlers.validator import router as validator_router
from app.handlers import dashboard
from app.scheduler import SchedulerService

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def validate_environment():
    """Validate all required environment variables at startup."""
    errors = []

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token or bot_token.startswith("your_"):
        errors.append("BOT_TOKEN is missing or not configured in .env")

    owner_id = os.getenv("OWNER_TELEGRAM_ID")
    if not owner_id or owner_id.startswith("your_"):
        errors.append("OWNER_TELEGRAM_ID is missing or not configured in .env")

    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    try:
        api_id_int = int(telegram_api_id or "0")
        if api_id_int == 0:
            errors.append("TELEGRAM_API_ID must be a valid integer (not 0 or empty)")
    except ValueError:
        errors.append(f"TELEGRAM_API_ID must be a valid integer, got: {telegram_api_id}")

    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")
    if not telegram_api_hash or telegram_api_hash.startswith("your_"):
        errors.append("TELEGRAM_API_HASH is missing or not configured in .env")

    if errors:
        logger.error("=" * 70)
        logger.error("STARTUP VALIDATION FAILED - Please configure .env file")
        logger.error("=" * 70)
        for error in errors:
            logger.error(f"  ❌ {error}")
        logger.error("=" * 70)
        logger.error("See .env.example for required variables")
        logger.error("=" * 70)
        raise ValueError("\n".join(errors))

    logger.info("✅ Environment validation passed")


validate_environment()
BOT_TOKEN = os.getenv("BOT_TOKEN")

scheduler_service = SchedulerService()


async def set_commands(bot: Bot):
    """Set bot commands."""
    commands = [BotCommand(command="start", description="Start the bot")]
    await bot.set_my_commands(commands)


async def main():
    """Main entry point."""
    logger.info("Initializing Cex Restore Panel...")

    init_db()

    os.makedirs("sessions", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(start_router)
    dp.include_router(accounts_router)
    dp.include_router(templates_router)
    dp.include_router(chats_router)
    dp.include_router(dashboard_router)
    dp.include_router(logs_router)
    dp.include_router(telethon_auth_router)
    dp.include_router(validator_router)

    # Pass scheduler to dashboard handler so it can access scheduler status
    dashboard.set_scheduler(scheduler_service)

    await set_commands(bot)

    await scheduler_service.start()

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot)
    finally:
        await scheduler_service.stop()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
