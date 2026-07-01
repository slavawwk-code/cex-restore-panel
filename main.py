import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.config import (
    ConfigurationError,
    Settings,
    ensure_runtime_directories,
    load_settings,
)
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


async def set_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Открыть главное меню"),
        BotCommand(command="account_disable", description="Отключить аккаунт по ID"),
        BotCommand(command="account_reauth", description="Сбросить авторизацию аккаунта"),
        BotCommand(command="account_delete", description="Удалить аккаунт по ID"),
    ]
    await bot.set_my_commands(commands)


async def run_bot(settings: Settings) -> None:
    """Initialize services and run polling until SIGINT or SIGTERM."""
    from app.database import init_db
    from app.handlers import (
        accounts,
        account_lifecycle_router,
        accounts_router,
        campaigns_router,
        chats_router,
        dashboard,
        dashboard_router,
        logs_router,
        proxy_router,
        start_router,
        telethon_auth_router,
        templates_router,
    )
    from app.handlers.validator import router as validator_router
    from app.scheduler import SchedulerService
    from app.services.proxy_monitor import ProxyMonitorService
    from app.services.account_orchestrator import account_orchestrator
    from app.services.autopilot_engine import autopilot_engine

    logger.info("Initializing Cex Restore Panel")
    init_db()

    bot = Bot(token=settings.bot_token)
    scheduler_service = SchedulerService(
        check_interval_seconds=settings.scheduler_interval_seconds
    )
    proxy_monitor = ProxyMonitorService(
        bot,
        interval_seconds=settings.proxy_monitor_interval_seconds,
        owner_telegram_id=settings.owner_telegram_id,
    )
    scheduler_started = False

    try:
        dispatcher = Dispatcher()
        dispatcher.include_router(start_router)
        dispatcher.include_router(accounts_router)
        dispatcher.include_router(account_lifecycle_router)
        dispatcher.include_router(templates_router)
        dispatcher.include_router(chats_router)
        dispatcher.include_router(dashboard_router)
        dispatcher.include_router(campaigns_router)
        dispatcher.include_router(logs_router)
        dispatcher.include_router(telethon_auth_router)
        dispatcher.include_router(proxy_router)
        dispatcher.include_router(validator_router)

        dashboard.set_scheduler(scheduler_service)
        accounts.set_scheduler(scheduler_service)

        await set_commands(bot)
        await account_orchestrator.start()
        await autopilot_engine.start()
        await scheduler_service.start()
        scheduler_started = True
        await proxy_monitor.start()

        logger.info(
            "Starting polling (DRY_RUN=%s, database=%s)",
            settings.dry_run,
            settings.database_path or "memory",
        )
        await dispatcher.start_polling(bot)
    finally:
        await autopilot_engine.stop()
        await proxy_monitor.stop()
        if scheduler_started:
            await scheduler_service.stop()
        await account_orchestrator.stop()
        await bot.session.close()
        logger.info("Bot stopped cleanly")


def run() -> int:
    """Validate configuration and start without tracebacks on setup errors."""
    os.umask(0o077)
    try:
        settings = load_settings(require_secrets=True)
        ensure_runtime_directories(settings)
    except ConfigurationError as error:
        print("Configuration error:", file=sys.stderr)
        for item in error.errors:
            print(f"  - {item}", file=sys.stderr)
        print("Create .env from .env.example and correct these values.", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Startup error: cannot create runtime directories: {error}", file=sys.stderr)
        return 2

    configure_logging(settings)
    logger.info("Environment validation passed")
    if not settings.dry_run:
        logger.warning("DRY_RUN is disabled; real sends are enabled")

    try:
        asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception:
        logger.exception("Fatal application error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
