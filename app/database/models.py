from datetime import UTC, datetime
import logging
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from app.config import ensure_runtime_directories, load_settings

runtime_settings = load_settings(require_secrets=False)
ensure_runtime_directories(runtime_settings)
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

engine = create_engine(
    runtime_settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


campaign_chats = Table(
    "campaign_chats",
    Base.metadata,
    Column("campaign_id", Integer, ForeignKey("campaigns.id"), primary_key=True),
    Column("chat_id", Integer, ForeignKey("chats.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    role = Column(String, nullable=False, default="operator")  # owner, operator
    created_at = Column(DateTime, default=utc_now)

    def __repr__(self):
        return f"<User {self.telegram_id} ({self.role})>"


class AdvertisingAccount(Base):
    __tablename__ = "advertising_accounts"

    id = Column(Integer, primary_key=True)
    display_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False, unique=True)
    telethon_session = Column(String, nullable=False)
    status = Column(String, nullable=False, default="warming", index=True)  # active, paused, warming, disabled
    created_at = Column(DateTime, default=utc_now)
    last_error = Column(String, nullable=True)

    # Telethon session fields
    session_connected = Column(Boolean, default=False, index=True)
    session_connected_at = Column(DateTime, nullable=True)
    session_last_checked_at = Column(DateTime, nullable=True)
    session_user_id = Column(String, nullable=True)
    session_username = Column(String, nullable=True)
    api_id = Column(Integer, nullable=True)
    api_hash = Column(String, nullable=True)
    session_file_path = Column(String, nullable=True)
    string_session = Column(Text, nullable=True)
    auth_status = Column(String, nullable=False, default="unverified", index=True)
    last_auth_error = Column(Text, nullable=True)
    health_score = Column(Integer, nullable=False, default=0)
    last_health_check = Column(DateTime, nullable=True)

    # Per-account proxy configuration
    proxy_enabled = Column(Boolean, nullable=False, default=False)
    proxy_type = Column(String, nullable=True)
    proxy_host = Column(String, nullable=True)
    proxy_port = Column(Integer, nullable=True)
    proxy_username = Column(String, nullable=True)
    proxy_password = Column(String, nullable=True)
    proxy_last_check_at = Column(DateTime, nullable=True)
    proxy_last_check_success = Column(Boolean, nullable=True)
    proxy_status = Column(String, nullable=False, default="unknown", index=True)
    proxy_last_checked_at = Column(DateTime, nullable=True)
    proxy_last_success_at = Column(DateTime, nullable=True)
    proxy_last_error = Column(String, nullable=True)
    proxy_latency_ms = Column(Integer, nullable=True)
    proxy_detected_type = Column(String, nullable=True)
    proxy_diagnostics = Column(Text, nullable=True)
    proxy_id = Column(Integer, nullable=True)
    orchestration_state = Column(String, nullable=False, default="CREATED", index=True)
    orchestration_error = Column(Text, nullable=True)
    orchestration_updated_at = Column(DateTime, nullable=True)
    autopilot_frozen_until = Column(DateTime, nullable=True, index=True)
    autopilot_freeze_reason = Column(Text, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    reauth_requested_at = Column(DateTime, nullable=True)
    lifecycle_updated_at = Column(DateTime, nullable=True)
    lifecycle_reason = Column(Text, nullable=True)
    login_attempt_count = Column(Integer, nullable=False, default=0)
    auth_generation = Column(Integer, nullable=False, default=0)
    device_model = Column(String, nullable=True)
    system_version = Column(String, nullable=True)
    app_version = Column(String, nullable=True)
    lang_code = Column(String, nullable=True)
    system_lang_code = Column(String, nullable=True)
    lang_pack = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    identity_created_at = Column(DateTime, nullable=True)

    chats = relationship("Chat", back_populates="account", cascade="all, delete-orphan")
    send_logs = relationship("SendLog", back_populates="account", cascade="all, delete-orphan")
    proxy_checks = relationship(
        "ProxyCheckHistory",
        back_populates="account",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<AdvertisingAccount {self.id} - {self.display_name} ({self.status})>"


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True)
    advertising_account_id = Column(Integer, ForeignKey("advertising_accounts.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    username_or_chat_id = Column(String, nullable=False)
    cooldown_minutes = Column(Integer, nullable=False, default=60)
    assigned_template_id = Column(Integer, ForeignKey("templates.id"), nullable=True, index=True)
    status = Column(String, nullable=False, default="active", index=True)  # active, paused, error
    is_active = Column(Boolean, default=True, index=True)
    last_sent_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    account = relationship("AdvertisingAccount", back_populates="chats")
    template = relationship("Template")
    send_logs = relationship("SendLog", back_populates="chat", cascade="all, delete-orphan")
    campaigns = relationship(
        "Campaign",
        secondary=campaign_chats,
        back_populates="chats",
    )

    def __repr__(self):
        return f"<Chat {self.id} - {self.title} ({self.status})>"


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<Template {self.id} - {self.name}>"


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("advertising_accounts.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True, index=True)
    interval_minutes = Column(Integer, nullable=False, default=60)
    status = Column(String, nullable=False, default="active", index=True)
    schedule_enabled = Column(Boolean, nullable=False, default=True)
    schedule_timezone = Column(String, nullable=False, default="Europe/Moscow")
    schedule_start_time = Column(String, nullable=True)
    schedule_end_time = Column(String, nullable=True)
    first_send_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    account = relationship("AdvertisingAccount")
    template = relationship("Template")
    chats = relationship(
        "Chat",
        secondary=campaign_chats,
        back_populates="campaigns",
    )

    def __repr__(self):
        return f"<Campaign {self.id} - {self.name} ({self.status})>"


class SendLog(Base):
    __tablename__ = "send_logs"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("advertising_accounts.id"), nullable=False, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    status = Column(String, nullable=False, index=True)  # success, error
    mode = Column(String, nullable=False, default="SIMULATION", index=True)  # SIMULATION, REAL
    error_message = Column(String, nullable=True)
    telegram_message_id = Column(Integer, nullable=True)
    sent_at = Column(DateTime, default=utc_now, index=True)

    account = relationship("AdvertisingAccount", back_populates="send_logs")
    chat = relationship("Chat", back_populates="send_logs")

    def __repr__(self):
        return f"<SendLog {self.id} - {self.status} ({self.mode}) at {self.sent_at}>"


class ProxyCheckHistory(Base):
    __tablename__ = "proxy_check_history"

    id = Column(Integer, primary_key=True)
    account_id = Column(
        Integer,
        ForeignKey("advertising_accounts.id"),
        nullable=False,
        index=True,
    )
    checked_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    status = Column(String, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)

    account = relationship("AdvertisingAccount", back_populates="proxy_checks")


class ProxyEndpoint(Base):
    """Reusable proxy registry used by the account orchestrator."""

    __tablename__ = "proxy_endpoints"

    id = Column(Integer, primary_key=True)
    proxy_type = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    status = Column(String, nullable=False, default="unknown", index=True)
    latency_ms = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    max_accounts = Column(Integer, nullable=False, default=10)
    score = Column(Integer, nullable=False, default=100)
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    disabled_until = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class AutopilotControlState(Base):
    """Single persisted snapshot of the system-level control state."""

    __tablename__ = "autopilot_control_state"

    id = Column(Integer, primary_key=True, default=1)
    system_state = Column(String, nullable=False, default="HEALTHY", index=True)
    action_taken = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    affected_accounts = Column(Integer, nullable=False, default=0)
    affected_proxies = Column(Integer, nullable=False, default=0)
    client_limit = Column(Integer, nullable=False, default=5)
    login_queue_paused = Column(Boolean, nullable=False, default=False)
    proxy_pool_paused = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


def init_db():
    """Initialize database tables."""
    from app.database.migrations import run_startup_migrations
    from app.services.device_identity import ensure_identity_for_all_accounts

    database_existed = bool(
        runtime_settings.database_path and runtime_settings.database_path.exists()
    )
    Base.metadata.create_all(bind=engine)
    run_startup_migrations(engine)
    session = SessionLocal()
    try:
        ensure_identity_for_all_accounts(session)
    finally:
        session.close()
    if runtime_settings.database_path is not None and not database_existed:
        runtime_settings.database_path.chmod(0o600)
    logger.info("Database initialized successfully")


def get_session():
    """Get a new database session."""
    return SessionLocal()
