from app.config import load_settings
from app.database.models import AdvertisingAccount


def get_api_credentials() -> tuple[int, str]:
    """Read and validate Telegram API credentials at call time."""
    settings = load_settings(require_secrets=True)
    return settings.telegram_api_id, settings.telegram_api_hash


def get_account_api_credentials(
    account: AdvertisingAccount,
) -> tuple[int, str]:
    """Use per-account API credentials when both are configured."""
    if account.api_id is None and not account.api_hash:
        return get_api_credentials()
    if not account.api_id or account.api_id <= 0 or not account.api_hash:
        raise ValueError("Для аккаунта должны быть заданы и api_id, и api_hash")
    return account.api_id, account.api_hash
