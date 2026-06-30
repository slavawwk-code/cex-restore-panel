#!/usr/bin/env python3
import asyncio
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def _exercise_async_services(settings) -> None:
    from aiogram import Bot

    from app.scheduler import SchedulerService
    from app.services.proxy_monitor import ProxyMonitorService

    async def no_database_cycle() -> None:
        return None

    scheduler = SchedulerService()
    scheduler._check_and_send = no_database_cycle
    await scheduler.start()
    await asyncio.sleep(0)
    if not scheduler.running:
        raise RuntimeError("scheduler did not enter running state")
    await scheduler.stop()

    bot = Bot(token=settings.bot_token)
    monitor = ProxyMonitorService(
        bot,
        interval_seconds=max(1, settings.proxy_monitor_interval_seconds),
        owner_telegram_id=settings.owner_telegram_id,
    )
    await monitor.start()
    await asyncio.sleep(0)
    if not monitor.running:
        raise RuntimeError("proxy monitor did not enter running state")
    await monitor.stop()
    await bot.session.close()


def main() -> int:
    try:
        from app.config import ensure_runtime_directories, load_settings
        from app.logging_config import configure_logging

        settings = load_settings(require_secrets=True)
        if not settings.dry_run:
            raise RuntimeError("DRY_RUN must be True for the first deployment")
        ensure_runtime_directories(settings)
        configure_logging(settings)
        configure_logging(settings)

        import logging

        if len(logging.getLogger().handlers) != 2:
            raise RuntimeError("logging handlers are duplicated or incomplete")

        modules = (
            "app.database.models",
            "app.handlers",
            "app.scheduler",
            "app.services.sender",
            "app.services.proxy_monitor",
            "app.telethon.client",
            "main",
        )
        for module_name in modules:
            importlib.import_module(module_name)

        from sqlalchemy import text

        from app.database import init_db
        from app.database.models import engine
        from app.services.sender import DRY_RUN as sender_dry_run

        if not sender_dry_run:
            raise RuntimeError("sender loaded with DRY_RUN disabled")
        init_db()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        asyncio.run(_exercise_async_services(settings))
    except Exception as error:
        print(
            f"Smoke test failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("Smoke test passed: imports, configuration, database, scheduler, bot, proxy monitor")
    print("No Telegram network connection was attempted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
