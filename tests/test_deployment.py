import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import (
    PROJECT_ROOT,
    ConfigurationError,
    ensure_runtime_directories,
    load_settings,
)
from app.logging_config import configure_logging


VALID_ENV = {
    "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456789",
    "OWNER_TELEGRAM_ID": "123456789",
    "TELEGRAM_API_ID": "12345",
    "TELEGRAM_API_HASH": "a" * 32,
    "DRY_RUN": "True",
    "LOG_LEVEL": "INFO",
    "TZ": "UTC",
    "SCHEDULER_CHECK_INTERVAL_SECONDS": "60",
    "PROXY_MONITOR_INTERVAL_SECONDS": "1800",
    "LOG_MAX_BYTES": "1048576",
    "LOG_BACKUP_COUNT": "2",
}


class DeploymentConfigurationTests(unittest.TestCase):
    def test_relative_paths_are_anchored_to_project_root(self):
        with patch.dict(
            "os.environ",
            {
                **VALID_ENV,
                "DATABASE_URL": "sqlite:///./data/test.db",
                "SESSIONS_DIR": "sessions",
                "LOGS_DIR": "logs",
                "BACKUP_DIR": "backups",
            },
            clear=False,
        ):
            settings = load_settings()

        self.assertEqual(settings.database_path, PROJECT_ROOT / "data/test.db")
        self.assertEqual(settings.sessions_dir, PROJECT_ROOT / "sessions")

    def test_missing_secrets_raise_readable_configuration_error(self):
        with patch.dict(
            "os.environ",
            {
                **VALID_ENV,
                "BOT_TOKEN": "your_bot_token",
                "TELEGRAM_API_HASH": "your_api_hash",
            },
            clear=False,
        ):
            with self.assertRaises(ConfigurationError) as context:
                load_settings()

        output = str(context.exception)
        self.assertIn("BOT_TOKEN", output)
        self.assertIn("TELEGRAM_API_HASH", output)
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWXYZ", output)

    def test_bootstrap_and_logging_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(
                "os.environ",
                {
                    **VALID_ENV,
                    "DATABASE_URL": f"sqlite:///{root / 'data/app.db'}",
                    "SESSIONS_DIR": str(root / "sessions"),
                    "LOGS_DIR": str(root / "logs"),
                    "BACKUP_DIR": str(root / "backups"),
                },
                clear=False,
            ):
                settings = load_settings()
                ensure_runtime_directories(settings)
                ensure_runtime_directories(settings)
                configure_logging(settings)
                configure_logging(settings)

            self.assertTrue(settings.sessions_dir.is_dir())
            self.assertTrue(settings.logs_dir.is_dir())
            self.assertTrue(settings.backup_dir.is_dir())
            root_logger = logging.getLogger()
            self.assertEqual(len(root_logger.handlers), 2)
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                handler.close()


if __name__ == "__main__":
    unittest.main()
