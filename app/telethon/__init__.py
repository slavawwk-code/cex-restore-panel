__all__ = ["TelethonClientManager"]


def __getattr__(name: str):
    """Avoid importing the client manager while session helpers initialize."""
    if name == "TelethonClientManager":
        from app.telethon.client import TelethonClientManager

        return TelethonClientManager
    raise AttributeError(name)
