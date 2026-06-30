import logging
import os
from logging.handlers import RotatingFileHandler

from app.config import Settings

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(settings: Settings) -> None:
    """Configure one console and one rotating file handler."""
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    log_path = settings.logs_dir / "cex-restore.log"
    log_existed = log_path.exists()
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    if not log_existed:
        os.chmod(log_path, 0o600)

    root_logger.setLevel(getattr(logging, settings.log_level))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
