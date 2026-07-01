import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database.models import AdvertisingAccount

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceIdentityProfile:
    device_model: str
    system_version: str
    app_version: str
    lang_code: str
    system_lang_code: str
    lang_pack: str
    timezone: str


WINDOWS_PROFILES = (
    DeviceIdentityProfile("Desktop", "Windows 11 x64", "5.16.3 x64", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 11 x64", "5.16.3 x64", "en", "en-US", "", "Europe/Warsaw"),
    DeviceIdentityProfile("Desktop", "Windows 11 Pro x64", "5.16.2 x64", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 10 x64", "5.16.3 x64", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 10 Pro x64", "5.16.1 x64", "en", "en-US", "", "Europe/Berlin"),
    DeviceIdentityProfile("Desktop", "Windows 11 x64", "5.15.9 x64", "ru", "ru-RU", "", "Asia/Dubai"),
    DeviceIdentityProfile("Desktop", "Windows 10 x64", "5.15.8 x64", "ru", "ru-RU", "", "Europe/Riga"),
    DeviceIdentityProfile("Desktop", "Windows 11 Home x64", "5.16.3 x64", "en", "en-GB", "", "Europe/London"),
    DeviceIdentityProfile("Desktop", "Windows 11 Pro x64", "5.16.0 x64", "ru", "ru-RU", "", "Europe/Minsk"),
    DeviceIdentityProfile("Desktop", "Windows 10 Enterprise x64", "5.15.7 x64", "en", "en-US", "", "Europe/Prague"),
    DeviceIdentityProfile("Desktop", "Windows 11 x64", "5.16.2 x64", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 10 x64", "5.16.0 x64", "en", "en-US", "", "Asia/Tbilisi"),
    DeviceIdentityProfile("Desktop", "Windows 11 x64", "5.15.9 x64", "ru", "ru-RU", "", "Europe/Vilnius"),
    DeviceIdentityProfile("Desktop", "Windows 10 Pro x64", "5.16.3 x64", "ru", "ru-RU", "", "Europe/Moscow"),
)

MAC_PROFILES = (
    DeviceIdentityProfile("MacBook Pro", "macOS 15.5", "5.16.3", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("MacBook Air", "macOS 14.7", "5.16.2", "en", "en-US", "", "Europe/Berlin"),
    DeviceIdentityProfile("iMac", "macOS 15.4", "5.16.1", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("Mac mini", "macOS 14.6", "5.15.9", "en", "en-GB", "", "Europe/London"),
)

LINUX_PROFILES = (
    DeviceIdentityProfile("Desktop", "Ubuntu 24.04", "5.16.3 x64", "ru", "ru-RU", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Ubuntu 22.04", "5.15.9 x64", "en", "en-US", "", "Europe/Warsaw"),
)

_RNG = random.SystemRandom()


def generate_identity_profile() -> DeviceIdentityProfile:
    """Generate a realistic Telegram Desktop identity profile once per account."""
    family = _RNG.choices(
        ("windows", "mac", "linux"),
        weights=(70, 20, 10),
        k=1,
    )[0]
    profiles = {
        "windows": WINDOWS_PROFILES,
        "mac": MAC_PROFILES,
        "linux": LINUX_PROFILES,
    }[family]
    return _RNG.choice(profiles)


def has_complete_identity(account: AdvertisingAccount) -> bool:
    return all(
        (
            account.device_model,
            account.system_version,
            account.app_version,
            account.lang_code,
            account.system_lang_code,
            account.identity_created_at,
        )
    )


def ensure_account_identity(account: AdvertisingAccount) -> bool:
    """Attach identity if missing. Returns True when fields were changed."""
    if has_complete_identity(account):
        return False
    apply_identity_profile(account, generate_identity_profile(), preserve_created_at=False)
    return True


def ensure_identity_for_all_accounts(session: Session) -> int:
    """Backfill identities for existing accounts without touching existing ones."""
    changed = 0
    for account in session.query(AdvertisingAccount).all():
        if ensure_account_identity(account):
            changed += 1
    if changed:
        session.commit()
        logger.info(
            "device_identity action=backfill result=success affected_accounts=%s",
            changed,
        )
    return changed


def regenerate_account_identity(account: AdvertisingAccount) -> None:
    """Owner-only manual reset; never called automatically."""
    apply_identity_profile(account, generate_identity_profile(), preserve_created_at=False)


def apply_identity_profile(
    account: AdvertisingAccount,
    profile: DeviceIdentityProfile,
    *,
    preserve_created_at: bool,
) -> None:
    account.device_model = profile.device_model
    account.system_version = profile.system_version
    account.app_version = profile.app_version
    account.lang_code = profile.lang_code
    account.system_lang_code = profile.system_lang_code
    account.lang_pack = profile.lang_pack
    account.timezone = profile.timezone
    if not preserve_created_at or account.identity_created_at is None:
        account.identity_created_at = datetime.now(UTC).replace(tzinfo=None)


def identity_telethon_kwargs(account: AdvertisingAccount) -> dict[str, str]:
    """Return stable Telethon device parameters for this account."""
    ensure_account_identity(account)
    return {
        "device_model": account.device_model,
        "system_version": account.system_version,
        "app_version": account.app_version,
        "lang_code": account.lang_code,
        "system_lang_code": account.system_lang_code,
        "lang_pack": account.lang_pack or "",
    }


def proxy_diagnostic_identity_kwargs() -> dict[str, str]:
    """Stable desktop identity for anonymous proxy connectivity checks."""
    return {
        "device_model": "Desktop",
        "system_version": "Windows 11 x64",
        "app_version": "5.16.3 x64",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
        "lang_pack": "",
    }
