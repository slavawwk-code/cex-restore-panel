import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)


class ConfigurationError(ValueError):
    """Raised when deployment configuration is missing or unsafe."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class Settings:
    project_root: Path
    env_file: Path
    bot_token: str | None
    owner_telegram_id: int | None
    telegram_api_id: int | None
    telegram_api_hash: str | None
    database_url: str
    database_path: Path | None
    sessions_dir: Path
    logs_dir: Path
    backup_dir: Path
    dry_run: bool
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    scheduler_interval_seconds: int
    proxy_monitor_interval_seconds: int
    orchestrator_max_clients: int
    orchestrator_login_concurrency: int
    orchestrator_health_batch_size: int
    orchestrator_global_delay_seconds: float
    orchestrator_account_delay_seconds: float
    orchestrator_login_max_retries: int
    autopilot_interval_seconds: int
    autopilot_queue_threshold: int
    autopilot_recovery_cooldown_seconds: int
    autopilot_healthy_clients: int


def load_settings(require_secrets: bool = True) -> Settings:
    """Load and validate runtime settings without logging secret values."""
    errors: list[str] = []

    bot_token = _optional_value("BOT_TOKEN")
    owner_id = _parse_positive_int("OWNER_TELEGRAM_ID", errors, required=require_secrets)
    api_id = _parse_positive_int("TELEGRAM_API_ID", errors, required=require_secrets)
    api_hash = _optional_value("TELEGRAM_API_HASH")

    if require_secrets:
        if not bot_token:
            errors.append("BOT_TOKEN is missing or still contains a placeholder")
        elif not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", bot_token):
            errors.append("BOT_TOKEN has an invalid format")
        if not api_hash:
            errors.append("TELEGRAM_API_HASH is missing or still contains a placeholder")
        elif not re.fullmatch(r"[A-Fa-f0-9]{32}", api_hash):
            errors.append("TELEGRAM_API_HASH must contain 32 hexadecimal characters")

    database_url, database_path = _database_settings(errors)
    dry_run = _parse_bool("DRY_RUN", "True", errors)
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    scheduler_interval = _parse_interval(
        "SCHEDULER_CHECK_INTERVAL_SECONDS", 60, errors, minimum=1, maximum=3600
    )
    proxy_interval = _parse_interval(
        "PROXY_MONITOR_INTERVAL_SECONDS", 1800, errors, minimum=0, maximum=86400
    )
    max_clients = _parse_interval(
        "ORCHESTRATOR_MAX_CLIENTS", 5, errors, minimum=1, maximum=10
    )
    login_concurrency = _parse_interval(
        "ORCHESTRATOR_LOGIN_CONCURRENCY", 3, errors, minimum=2, maximum=5
    )
    health_batch_size = _parse_interval(
        "ORCHESTRATOR_HEALTH_BATCH_SIZE", 4, errors, minimum=3, maximum=5
    )
    global_delay = _parse_float(
        "ORCHESTRATOR_GLOBAL_DELAY_SECONDS", 0.25, errors, minimum=0.0, maximum=10.0
    )
    account_delay = _parse_float(
        "ORCHESTRATOR_ACCOUNT_DELAY_SECONDS", 1.0, errors, minimum=0.0, maximum=60.0
    )
    login_max_retries = _parse_interval(
        "ORCHESTRATOR_LOGIN_MAX_RETRIES", 3, errors, minimum=1, maximum=5
    )
    autopilot_interval = _parse_interval(
        "AUTOPILOT_INTERVAL_SECONDS", 15, errors, minimum=10, maximum=30
    )
    autopilot_queue_threshold = _parse_interval(
        "AUTOPILOT_QUEUE_THRESHOLD", 20, errors, minimum=5, maximum=1000
    )
    autopilot_recovery_cooldown = _parse_interval(
        "AUTOPILOT_RECOVERY_COOLDOWN_SECONDS",
        300,
        errors,
        minimum=60,
        maximum=86400,
    )
    autopilot_healthy_clients = _parse_interval(
        "AUTOPILOT_HEALTHY_CLIENTS", 5, errors, minimum=5, maximum=10
    )
    log_max_bytes = _parse_interval(
        "LOG_MAX_BYTES", 10_485_760, errors, minimum=1_048_576, maximum=1_073_741_824
    )
    log_backup_count = _parse_interval(
        "LOG_BACKUP_COUNT", 5, errors, minimum=1, maximum=100
    )
    timezone_name = os.getenv("TZ", "Europe/Moscow").strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        errors.append(f"TZ is not a valid IANA timezone: {timezone_name or '(empty)'}")

    sessions_dir = _directory_setting("SESSIONS_DIR", "sessions", errors)
    logs_dir = _directory_setting("LOGS_DIR", "logs", errors)
    backup_dir = _directory_setting("BACKUP_DIR", "backups", errors)

    if errors:
        raise ConfigurationError(errors)

    return Settings(
        project_root=PROJECT_ROOT,
        env_file=ENV_FILE,
        bot_token=bot_token,
        owner_telegram_id=owner_id,
        telegram_api_id=api_id,
        telegram_api_hash=api_hash,
        database_url=database_url,
        database_path=database_path,
        sessions_dir=sessions_dir,
        logs_dir=logs_dir,
        backup_dir=backup_dir,
        dry_run=dry_run,
        log_level=log_level,
        log_max_bytes=log_max_bytes,
        log_backup_count=log_backup_count,
        scheduler_interval_seconds=scheduler_interval,
        proxy_monitor_interval_seconds=proxy_interval,
        orchestrator_max_clients=max_clients,
        orchestrator_login_concurrency=login_concurrency,
        orchestrator_health_batch_size=health_batch_size,
        orchestrator_global_delay_seconds=global_delay,
        orchestrator_account_delay_seconds=account_delay,
        orchestrator_login_max_retries=login_max_retries,
        autopilot_interval_seconds=autopilot_interval,
        autopilot_queue_threshold=autopilot_queue_threshold,
        autopilot_recovery_cooldown_seconds=autopilot_recovery_cooldown,
        autopilot_healthy_clients=autopilot_healthy_clients,
    )


def ensure_runtime_directories(settings: Settings) -> None:
    """Create all writable runtime directories required on first startup."""
    directories = {
        settings.sessions_dir,
        settings.logs_dir,
        settings.backup_dir,
    }
    if settings.database_path is not None:
        directories.add(settings.database_path.parent)
    for directory in directories:
        created = not directory.exists()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if created:
            directory.chmod(0o700)


def _optional_value(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith("your_"):
        return None
    return value


def _parse_positive_int(
    name: str, errors: list[str], required: bool
) -> int | None:
    raw_value = _optional_value(name)
    if raw_value is None:
        if required:
            errors.append(f"{name} is missing or still contains a placeholder")
        return None
    try:
        value = int(raw_value)
    except ValueError:
        errors.append(f"{name} must be a positive integer")
        return None
    if value <= 0:
        errors.append(f"{name} must be a positive integer")
        return None
    return value


def _parse_bool(name: str, default: str, errors: list[str]) -> bool:
    raw_value = os.getenv(name, default).strip().lower()
    if raw_value not in {"true", "false"}:
        errors.append(f"{name} must be True or False")
        return True
    return raw_value == "true"


def _parse_interval(
    name: str,
    default: int,
    errors: list[str],
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError:
        errors.append(f"{name} must be an integer")
        return default
    if value < minimum:
        errors.append(f"{name} must be at least {minimum}")
        return default
    if value > maximum:
        errors.append(f"{name} must not exceed {maximum}")
        return default
    return value


def _parse_float(
    name: str,
    default: float,
    errors: list[str],
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(os.getenv(name, str(default)).strip())
    except ValueError:
        errors.append(f"{name} must be a number")
        return default
    if not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}")
        return default
    return value


def _resolve_directory(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _directory_setting(name: str, default: str, errors: list[str]) -> Path:
    value = os.getenv(name, default).strip()
    if not value:
        errors.append(f"{name} must not be empty")
        value = default
    return _resolve_directory(value)


def _database_settings(errors: list[str]) -> tuple[str, Path | None]:
    raw_url = os.getenv("DATABASE_URL", "sqlite:///./data/cex_restore.db").strip()
    if not raw_url:
        errors.append("DATABASE_URL must not be empty")
        raw_url = "sqlite:///./data/cex_restore.db"
    if raw_url == "sqlite:///:memory:":
        return raw_url, None
    if not raw_url.startswith("sqlite:///"):
        errors.append("DATABASE_URL must use SQLite (sqlite:///path/to/database.db)")
        return raw_url, None
    raw_path = raw_url.removeprefix("sqlite:///")
    database_path = Path(raw_path).expanduser()
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    database_path = database_path.resolve()
    return f"sqlite:///{database_path}", database_path
