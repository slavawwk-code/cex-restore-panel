from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/cex_restore.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    role = Column(String, nullable=False, default="operator")  # owner, operator
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.telegram_id} ({self.role})>"


class AdvertisingAccount(Base):
    __tablename__ = "advertising_accounts"

    id = Column(Integer, primary_key=True)
    display_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False, unique=True)
    telethon_session = Column(String, nullable=False)
    status = Column(String, nullable=False, default="warming", index=True)  # active, paused, warming, disabled
    created_at = Column(DateTime, default=datetime.utcnow)
    last_error = Column(String, nullable=True)

    # Telethon session fields
    session_connected = Column(Boolean, default=False, index=True)
    session_connected_at = Column(DateTime, nullable=True)
    session_last_checked_at = Column(DateTime, nullable=True)
    session_user_id = Column(String, nullable=True)
    session_username = Column(String, nullable=True)

    chats = relationship("Chat", back_populates="account", cascade="all, delete-orphan")
    send_logs = relationship("SendLog", back_populates="account", cascade="all, delete-orphan")

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
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("AdvertisingAccount", back_populates="chats")
    template = relationship("Template")
    send_logs = relationship("SendLog", back_populates="chat", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Chat {self.id} - {self.title} ({self.status})>"


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Template {self.id} - {self.name}>"


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
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)

    account = relationship("AdvertisingAccount", back_populates="send_logs")
    chat = relationship("Chat", back_populates="send_logs")

    def __repr__(self):
        return f"<SendLog {self.id} - {self.status} ({self.mode}) at {self.sent_at}>"


def init_db():
    """Initialize database tables."""
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully.")


def get_session():
    """Get a new database session."""
    return SessionLocal()
