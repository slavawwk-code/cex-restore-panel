#!/usr/bin/env python3
import asyncio
import os
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    failures: list[str] = []
    successes: list[str] = []

    try:
        from app.config import ConfigurationError, load_settings

        settings = load_settings(require_secrets=True)
        successes.append("environment variables are valid")
    except ConfigurationError as error:
        failures.extend(error.errors)
        return _report(successes, failures)

    for label, directory in (
        ("sessions directory", settings.sessions_dir),
        ("logs directory", settings.logs_dir),
        ("backup directory", settings.backup_dir),
    ):
        if directory.is_dir() and os.access(directory, os.R_OK | os.W_OK | os.X_OK):
            successes.append(f"{label} is writable")
            if _is_private(directory):
                successes.append(f"{label} permissions are private")
            else:
                failures.append(f"{label} permissions are too broad: {directory}")
        else:
            failures.append(f"{label} is missing or not writable: {directory}")

    if settings.database_path is None or not settings.database_path.is_file():
        failures.append("SQLite database file does not exist; run smoke_test.py first")
    else:
        try:
            from sqlalchemy import inspect, text
            from app.database.models import engine

            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            tables = set(inspect(engine).get_table_names())
            if "advertising_accounts" not in tables:
                failures.append("database schema is not initialized")
            else:
                successes.append("database is reachable and initialized")
                if _is_private(settings.database_path):
                    successes.append("database permissions are private")
                else:
                    failures.append("database permissions allow group/other access")
        except Exception as error:
            failures.append(f"database check failed: {type(error).__name__}: {error}")

    try:
        asyncio.run(_exercise_service_lifecycles(settings))
        successes.append(
            f"scheduler lifecycle is healthy ({settings.scheduler_interval_seconds}s interval)"
        )
    except Exception as error:
        failures.append(f"scheduler/proxy monitor check failed: {type(error).__name__}: {error}")

    try:
        from app.telethon.config import get_api_credentials

        api_id, api_hash = get_api_credentials()
        assert api_id == settings.telegram_api_id and api_hash == settings.telegram_api_hash
        successes.append("Telethon configuration is valid")
    except Exception as error:
        failures.append(f"Telethon configuration failed: {type(error).__name__}: {error}")

    try:
        from app.services.proxy_monitor import ProxyMonitorService

        assert callable(ProxyMonitorService.start) and callable(ProxyMonitorService.stop)
        monitor_state = (
            "disabled by configuration"
            if settings.proxy_monitor_interval_seconds == 0
            else f"configured ({settings.proxy_monitor_interval_seconds}s interval)"
        )
        successes.append(f"proxy monitor is {monitor_state}")
    except Exception as error:
        failures.append(f"proxy monitor check failed: {type(error).__name__}: {error}")

    if settings.dry_run:
        successes.append("DRY_RUN is enabled")
    else:
        failures.append("DRY_RUN must remain True for the first deployment")

    successes.append("Telegram bot token passed local format validation")
    if settings.env_file.is_file():
        if _is_private(settings.env_file):
            successes.append(".env permissions are private")
        else:
            failures.append(".env permissions allow group/other access; use chmod 600 .env")
    for session_file in settings.sessions_dir.glob("*.session"):
        if not _is_private(session_file):
            failures.append(f"session permissions are too broad: {session_file.name}")
    return _report(successes, failures)


def _report(successes: list[str], failures: list[str]) -> int:
    for message in successes:
        print(f"[OK] {message}")
    for message in failures:
        print(f"[FAIL] {message}", file=sys.stderr)
    print(f"Health check: {'HEALTHY' if not failures else 'UNHEALTHY'}")
    return 0 if not failures else 1


def _is_private(path: Path) -> bool:
    return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


async def _exercise_service_lifecycles(settings) -> None:
    from app.scheduler import SchedulerService
    from app.services.proxy_monitor import ProxyMonitorService

    async def no_database_cycle() -> None:
        return None

    scheduler = SchedulerService(settings.scheduler_interval_seconds)
    scheduler._check_and_send = no_database_cycle
    await scheduler.start()
    await asyncio.sleep(0)
    if not scheduler.running:
        raise RuntimeError("scheduler did not start")
    await scheduler.stop()

    monitor = ProxyMonitorService(
        bot=object(),
        interval_seconds=max(1, settings.proxy_monitor_interval_seconds),
        owner_telegram_id=settings.owner_telegram_id,
    )
    await monitor.start()
    await asyncio.sleep(0)
    if not monitor.running:
        raise RuntimeError("proxy monitor did not start")
    await monitor.stop()


if __name__ == "__main__":
    raise SystemExit(main())
