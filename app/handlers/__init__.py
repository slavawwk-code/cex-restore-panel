from app.handlers.start import router as start_router
from app.handlers.accounts import router as accounts_router
from app.handlers.templates import router as templates_router
from app.handlers.chats import router as chats_router
from app.handlers.dashboard import router as dashboard_router
from app.handlers.logs import router as logs_router
from app.handlers.telethon_auth import router as telethon_auth_router

__all__ = ["start_router", "accounts_router", "templates_router", "chats_router", "dashboard_router", "logs_router", "telethon_auth_router"]
