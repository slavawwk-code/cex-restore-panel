from app.config import load_settings


def get_api_credentials() -> tuple[int, str]:
    """Read and validate Telegram API credentials at call time."""
    settings = load_settings(require_secrets=True)
    return settings.telegram_api_id, settings.telegram_api_hash
