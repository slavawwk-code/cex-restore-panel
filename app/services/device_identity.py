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
    DeviceIdentityProfile("Desktop", "Windows 11 Home x64", "5.16.3 x64", "ru", "ru", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 11 Pro x64", "5.16.3 x64", "ru", "ru", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 10 Pro x64", "5.16.3 x64", "ru", "ru", "", "Europe/Moscow"),
    DeviceIdentityProfile("Desktop", "Windows 11 Home x64", "5.16.2 x64", "ru", "ru", "", "Europe/Minsk"),
    DeviceIdentityProfile("Desktop", "Windows 10 Home x64", "5.16.1 x64", "ru", "ru", "", "Europe/Moscow"),
)

MAC_PROFILES = (
    DeviceIdentityProfile("MacBook Pro", "macOS 15.5", "5.16", "ru", "ru", "", "Europe/Moscow"),
    DeviceIdentityProfile("MacBook Air", "macOS 14.7", "5.16", "ru", "ru", "", "Europe/Moscow"),
    DeviceIdentityProfile("iMac", "macOS 15.4", "5.16", "ru", "ru", "", "Europe/Moscow"),
)

LINUX_PROFILES = (
    DeviceIdentityProfile("Ubuntu Desktop", "Ubuntu 24.04", "5.16", "ru", "ru", "", "Europe/Moscow"),
    DeviceIdentityProfile("Ubuntu Desktop", "Ubuntu 22.04", "5.16", "ru", "ru", "", "Europe/Moscow"),
)

_RNG = random.SystemRandom()
ALLOWED_TELETHON_IDENTITY_KWARGS = frozenset(
    {
        "device_model",
        "system_version",
        "app_version",
        "lang_code",
        "system_lang_code",
    }
)


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
    profile = _RNG.choice(profiles)
    validate_identity_profile(profile)
    return profile


def validate_identity_profile(profile: DeviceIdentityProfile) -> None:
    """Reject impossible Telegram Desktop identity combinations."""
    combined = " ".join(
        (
            profile.device_model,
            profile.system_version,
            profile.app_version,
            profile.lang_code,
            profile.system_lang_code,
            profile.lang_pack,
            profile.timezone,
        )
    ).lower()
    if "viper" in combined:
        raise ValueError("identity profile contains forbidden device name")
    if "ios" in combined or "android" in combined:
        raise ValueError("mobile OS is not valid for Telegram Desktop identity")
    device = profile.device_model.lower()
    system = profile.system_version.lower()
    if "macbook" in device and "windows" in system:
        raise ValueError("MacBook device cannot use Windows system version")
    if "ubuntu" in device and "windows" in system:
        raise ValueError("Ubuntu device cannot use Windows system version")
    if device == "desktop" and ("ios" in system or "android" in system):
        raise ValueError("Desktop device cannot use mobile system version")
    if "windows" in system and device != "desktop":
        raise ValueError("Windows Telegram Desktop profile must use Desktop device")
    if ("macbook" in device or "imac" in device or "mac mini" in device) and "macos" not in system:
        raise ValueError("Apple desktop profile must use macOS system version")
    if "ubuntu" in device and not ("ubuntu" in system or "linux" in system):
        raise ValueError("Linux desktop profile must use Ubuntu/Linux system version")


def _account_identity_profile(account: AdvertisingAccount) -> DeviceIdentityProfile:
    return DeviceIdentityProfile(
        account.device_model or "",
        account.system_version or "",
        account.app_version or "",
        account.lang_code or "",
        account.system_lang_code or "",
        account.lang_pack or "",
        account.timezone or "",
    )


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
        try:
            validate_identity_profile(_account_identity_profile(account))
            return False
        except ValueError:
            logger.warning(
                "device_identity account_id=%s action=repair_invalid result=started",
                getattr(account, "id", None),
            )
            apply_identity_profile(
                account,
                generate_identity_profile(),
                preserve_created_at=False,
            )
            return True
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
    return sanitize_telethon_identity_kwargs(
        {
            "device_model": account.device_model,
            "system_version": account.system_version,
            "app_version": account.app_version,
            "lang_code": account.lang_code,
            "system_lang_code": account.system_lang_code,
        }
    )


def sanitize_telethon_identity_kwargs(values: dict) -> dict[str, str]:
    """Drop identity fields unsupported by Telethon 1.44 TelegramClient."""
    return {
        key: value
        for key, value in values.items()
        if key in ALLOWED_TELETHON_IDENTITY_KWARGS and value is not None
    }


def proxy_diagnostic_identity_kwargs() -> dict[str, str]:
    """Stable desktop identity for anonymous proxy connectivity checks."""
    return sanitize_telethon_identity_kwargs(
        {
            "device_model": "Desktop",
            "system_version": "Windows 11 x64",
            "app_version": "5.16.3 x64",
            "lang_code": "ru",
            "system_lang_code": "ru-RU",
        }
    )
