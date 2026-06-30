from app.database.models import AdvertisingAccount


def build_proxy(account: AdvertisingAccount) -> dict | None:
    """Build a Telethon-compatible proxy configuration for an account."""
    if not account.proxy_enabled:
        return None

    return {
        "proxy_type": account.proxy_type.lower(),
        "addr": account.proxy_host,
        "port": account.proxy_port,
        "rdns": True,
        "username": account.proxy_username or None,
        "password": account.proxy_password or None,
    }


def proxy_signature(account: AdvertisingAccount) -> tuple | None:
    """Return a non-logged fingerprint used to refresh cached clients."""
    if not account.proxy_enabled:
        return None

    return (
        account.proxy_type,
        account.proxy_host,
        account.proxy_port,
        account.proxy_username,
        account.proxy_password,
    )
