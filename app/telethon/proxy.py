from app.database.models import AdvertisingAccount


def resolve_telethon_proxy_type(proxy_type: str):
    """Return a Telethon/python-socks compatible proxy protocol object."""
    normalized = (proxy_type or "").upper()
    try:
        from python_socks import ProxyType

        return {
            "SOCKS5": ProxyType.SOCKS5,
            "SOCKS4": ProxyType.SOCKS4,
            "HTTP": ProxyType.HTTP,
        }[normalized]
    except ImportError:
        try:
            import socks

            return {
                "SOCKS5": socks.SOCKS5,
                "SOCKS4": socks.SOCKS4,
                "HTTP": socks.HTTP,
            }[normalized]
        except ImportError:
            return {
                "SOCKS5": "socks5",
                "SOCKS4": "socks4",
                "HTTP": "http",
            }[normalized]


def build_telethon_proxy_config(
    proxy_type: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> dict:
    """Build a Telethon 1.44 compatible proxy configuration."""
    return {
        "proxy_type": resolve_telethon_proxy_type(proxy_type),
        "addr": host,
        "port": int(port),
        "rdns": True,
        "username": username or None,
        "password": password or None,
    }


def build_proxy(account: AdvertisingAccount) -> dict | None:
    """Build a Telethon-compatible proxy configuration for an account."""
    if not account.proxy_enabled:
        return None

    return build_telethon_proxy_config(
        account.proxy_type,
        account.proxy_host,
        account.proxy_port,
        account.proxy_username,
        account.proxy_password,
    )


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
