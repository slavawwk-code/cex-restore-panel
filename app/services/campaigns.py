import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.database.models import AdvertisingAccount, Campaign, Chat, Template
from app.services.sender import send_message

logger = logging.getLogger(__name__)


@dataclass
class CampaignSendSummary:
    sent_count: int = 0
    skipped_count: int = 0
    errors_count: int = 0
    reasons: list[str] = field(default_factory=list)
    next_send_at: datetime | None = None

    @property
    def total(self) -> int:
        return self.sent_count + self.skipped_count + self.errors_count


def list_campaigns(session: Session, include_inactive: bool = False) -> list[Campaign]:
    """Return campaigns ordered by newest first."""
    query = session.query(Campaign)
    if not include_inactive:
        query = query.filter(Campaign.status == "active")
    return query.order_by(Campaign.id.desc()).all()


def get_campaign(session: Session, campaign_id: int) -> Campaign | None:
    """Return a campaign by id."""
    return session.query(Campaign).filter(Campaign.id == campaign_id).first()


def create_campaign(
    session: Session,
    name: str,
    account_id: int,
    template_id: int | None,
    interval_minutes: int = 60,
    chat_ids: list[int] | None = None,
) -> Campaign:
    """Create a campaign without mutating unrelated chats."""
    account = session.query(AdvertisingAccount).filter(AdvertisingAccount.id == account_id).first()
    if not account:
        raise ValueError("Аккаунт не найден")
    if template_id is not None:
        template = session.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise ValueError("Шаблон не найден")

    campaign = Campaign(
        name=name.strip(),
        account_id=account_id,
        template_id=template_id,
        interval_minutes=validate_interval_minutes(interval_minutes),
    )
    if chat_ids:
        campaign.chats = _load_campaign_chats(session, account_id, chat_ids)
    session.add(campaign)
    session.commit()
    logger.info(
        "campaign action=create result=success campaign_id=%s account_id=%s",
        campaign.id,
        account_id,
    )
    return campaign


def schedule_campaign_first_send(
    session: Session,
    campaign_id: int,
    delay_minutes: int | None,
) -> Campaign:
    """Set or clear an optional first-send override without changing interval."""
    campaign = _require_campaign(session, campaign_id)
    if delay_minutes is None:
        campaign.first_send_at = None
    else:
        if delay_minutes < 0:
            raise ValueError("Задержка первой отправки не может быть отрицательной")
        campaign.first_send_at = datetime.utcnow() + timedelta(minutes=delay_minutes)
    session.commit()
    logger.info(
        "campaign action=schedule_first_send result=success campaign_id=%s delay=%s",
        campaign_id,
        delay_minutes,
    )
    return campaign


async def run_campaign_once(
    session: Session,
    campaign_id: int,
    *,
    ignore_cooldown: bool = True,
) -> CampaignSendSummary:
    """Run one immediate send cycle for a single campaign only."""
    campaign = _require_campaign(session, campaign_id)
    summary = CampaignSendSummary()

    if campaign.status != "active":
        summary.skipped_count += 1
        summary.reasons.append("Кампания не активна")
        summary.next_send_at = calculate_campaign_next_send_at(campaign)
        return summary
    if not campaign.account:
        summary.skipped_count += 1
        summary.reasons.append("Аккаунт кампании не найден")
        return summary
    if campaign.account.status != "active":
        summary.skipped_count += 1
        summary.reasons.append("Аккаунт не активен")
        summary.next_send_at = calculate_campaign_next_send_at(campaign)
        return summary
    if not campaign.template or not campaign.template.is_active:
        summary.skipped_count += 1
        summary.reasons.append("Нет активного шаблона")
        summary.next_send_at = calculate_campaign_next_send_at(campaign)
        return summary
    active_chats = [chat for chat in campaign.chats if chat.is_active and chat.status == "active"]
    if not active_chats:
        summary.skipped_count += 1
        summary.reasons.append("Нет активных чатов")
        summary.next_send_at = calculate_campaign_next_send_at(campaign)
        return summary

    for chat in active_chats:
        try:
            result = await send_message(
                session,
                campaign.account,
                chat,
                campaign.template,
                interval_minutes=campaign.interval_minutes,
                ignore_cooldown=ignore_cooldown,
            )
            if result.get("success"):
                summary.sent_count += 1
            elif result.get("mode") == "SKIPPED":
                summary.skipped_count += 1
                if result.get("error_message"):
                    summary.reasons.append(result["error_message"])
            else:
                summary.errors_count += 1
                if result.get("error_message"):
                    summary.reasons.append(result["error_message"])
        except Exception as exc:
            logger.error(
                "campaign action=manual_send result=error campaign_id=%s chat_id=%s error=%s",
                campaign.id,
                chat.id,
                exc,
                exc_info=True,
            )
            summary.errors_count += 1
            summary.reasons.append(str(exc))

    campaign.first_send_at = None
    session.commit()
    session.refresh(campaign)
    summary.next_send_at = calculate_campaign_next_send_at(campaign)
    logger.info(
        "campaign action=manual_send result=success campaign_id=%s sent=%s skipped=%s errors=%s",
        campaign.id,
        summary.sent_count,
        summary.skipped_count,
        summary.errors_count,
    )
    return summary


def rename_campaign(session: Session, campaign_id: int, new_name: str) -> Campaign:
    """Rename a campaign in-place."""
    campaign = _require_campaign(session, campaign_id)
    name = new_name.strip()
    if not name:
        raise ValueError("Название кампании не может быть пустым")
    campaign.name = name[:100]
    session.commit()
    logger.info("campaign action=rename result=success campaign_id=%s", campaign_id)
    return campaign


def update_campaign_template(
    session: Session,
    campaign_id: int,
    template_id: int,
) -> Campaign:
    """Change campaign template for future sends only."""
    campaign = _require_campaign(session, campaign_id)
    template = session.query(Template).filter(
        Template.id == template_id,
        Template.is_active == True,  # noqa: E712
    ).first()
    if not template:
        raise ValueError("Активный шаблон не найден")
    campaign.template_id = template.id
    session.commit()
    logger.info(
        "campaign action=change_template result=success campaign_id=%s template_id=%s",
        campaign_id,
        template_id,
    )
    return campaign


def update_campaign_interval(
    session: Session,
    campaign_id: int,
    interval_minutes: int,
) -> Campaign:
    """Change interval in-place; scheduler reads this value every cycle."""
    campaign = _require_campaign(session, campaign_id)
    campaign.interval_minutes = validate_interval_minutes(interval_minutes)
    session.commit()
    logger.info(
        "campaign action=change_interval result=success campaign_id=%s interval=%s",
        campaign_id,
        campaign.interval_minutes,
    )
    return campaign


def update_campaign_schedule(
    session: Session,
    campaign_id: int,
    *,
    enabled: bool,
    start_time: str | None = None,
    end_time: str | None = None,
    timezone: str = "Europe/Moscow",
) -> Campaign:
    """Update simple campaign schedule fields in-place."""
    campaign = _require_campaign(session, campaign_id)
    if start_time:
        validate_time_hhmm(start_time)
    if end_time:
        validate_time_hhmm(end_time)
    campaign.schedule_enabled = enabled
    campaign.schedule_start_time = start_time
    campaign.schedule_end_time = end_time
    campaign.schedule_timezone = timezone or "Europe/Moscow"
    session.commit()
    logger.info("campaign action=configure_schedule result=success campaign_id=%s", campaign_id)
    return campaign


def set_campaign_chats(
    session: Session,
    campaign_id: int,
    chat_ids: list[int],
) -> Campaign:
    """Replace campaign chat assignment after explicit operator confirmation."""
    campaign = _require_campaign(session, campaign_id)
    campaign.chats = _load_campaign_chats(session, campaign.account_id, chat_ids)
    session.commit()
    logger.info(
        "campaign action=set_chats result=success campaign_id=%s chat_count=%s",
        campaign_id,
        len(campaign.chats),
    )
    return campaign


def get_effective_campaign_for_chat(session: Session, chat_id: int) -> Campaign | None:
    """Return the first active scheduled campaign that owns this chat."""
    campaigns = (
        session.query(Campaign)
        .join(Campaign.chats)
        .filter(
            Chat.id == chat_id,
            Campaign.status == "active",
            Campaign.schedule_enabled == True,  # noqa: E712
        )
        .order_by(Campaign.id.asc())
        .all()
    )
    for campaign in campaigns:
        if campaign.first_send_at and datetime.utcnow() < campaign.first_send_at:
            continue
        if is_campaign_inside_schedule(campaign):
            return campaign
    return None


def mark_campaign_first_send_consumed(session: Session, campaign: Campaign) -> None:
    if campaign.first_send_at is not None:
        campaign.first_send_at = None
        session.flush()


def calculate_campaign_next_send_at(campaign: Campaign) -> datetime | None:
    """Best-effort next send estimate for UI."""
    if campaign.first_send_at:
        return campaign.first_send_at
    if campaign.status != "active" or not campaign.schedule_enabled:
        return None
    active_chats = [chat for chat in campaign.chats if chat.is_active and chat.status == "active"]
    if not active_chats:
        return None
    candidates = []
    for chat in active_chats:
        if chat.last_sent_at:
            candidates.append(chat.last_sent_at + timedelta(minutes=campaign.interval_minutes))
        else:
            candidates.append(datetime.utcnow())
    return min(candidates) if candidates else None


def is_campaign_inside_schedule(campaign: Campaign, now: datetime | None = None) -> bool:
    """Check optional campaign time window."""
    if not campaign.schedule_enabled:
        return False
    if not campaign.schedule_start_time and not campaign.schedule_end_time:
        return True
    try:
        tz = ZoneInfo(campaign.schedule_timezone or "Europe/Moscow")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Europe/Moscow")
    current = now.astimezone(tz) if now and now.tzinfo else (now or datetime.now(tz))
    current_minutes = current.hour * 60 + current.minute
    start = _time_to_minutes(campaign.schedule_start_time or "00:00")
    end = _time_to_minutes(campaign.schedule_end_time or "23:59")
    if start <= end:
        return start <= current_minutes <= end
    return current_minutes >= start or current_minutes <= end


def validate_interval_minutes(value: int) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Интервал должен быть числом минут") from exc
    if interval < 1 or interval > 1440:
        raise ValueError("Интервал должен быть от 1 до 1440 минут")
    return interval


def validate_time_hhmm(value: str) -> str:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Время должно быть в формате HH:MM")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError as exc:
        raise ValueError("Время должно быть в формате HH:MM") from exc
    if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
        raise ValueError("Время должно быть в формате HH:MM")
    return f"{hours:02d}:{minutes:02d}"


def parse_schedule_window(value: str) -> tuple[str, str]:
    raw = value.strip().replace("—", "-").replace("–", "-")
    if "-" not in raw:
        raise ValueError("Расписание должно быть в формате HH:MM-HH:MM")
    start_raw, end_raw = raw.split("-", 1)
    return validate_time_hhmm(start_raw.strip()), validate_time_hhmm(end_raw.strip())


def format_campaign_card(campaign: Campaign) -> str:
    template_name = campaign.template.name if campaign.template else "не назначен"
    account_name = campaign.account.display_name if campaign.account else "не найден"
    chat_count = len(campaign.chats or [])
    schedule = "включено" if campaign.schedule_enabled else "выключено"
    if campaign.schedule_start_time or campaign.schedule_end_time:
        schedule = (
            f"{campaign.schedule_start_time or '00:00'}"
            f"–{campaign.schedule_end_time or '23:59'}"
        )
    next_send = calculate_campaign_next_send_at(campaign)
    next_send_text = next_send.strftime("%H:%M") if next_send else "—"
    return (
        f"<b>{campaign.name}</b>\n\n"
        f"Аккаунт\n{account_name}\n\n"
        f"Шаблон\n{template_name}\n\n"
        f"Интервал\n{campaign.interval_minutes} мин.\n\n"
        f"Чаты\n{chat_count}\n\n"
        f"Расписание\n{schedule}\n\n"
        f"Следующая отправка\n{next_send_text}"
    )


def format_campaign_send_summary(summary: CampaignSendSummary) -> str:
    next_send = summary.next_send_at.strftime("%H:%M") if summary.next_send_at else "—"
    text = (
        "Тестовая отправка завершена.\n\n"
        f"Отправлено: {summary.sent_count}\n"
        f"Пропущено: {summary.skipped_count}\n"
        f"Ошибки: {summary.errors_count}\n"
        f"Следующая отправка: {next_send}"
    )
    if summary.reasons:
        unique_reasons = []
        for reason in summary.reasons:
            if reason and reason not in unique_reasons:
                unique_reasons.append(reason)
        text += "\n\nПричины:\n" + "\n".join(f"- {reason}" for reason in unique_reasons[:5])
    return text


def _require_campaign(session: Session, campaign_id: int) -> Campaign:
    campaign = get_campaign(session, campaign_id)
    if not campaign:
        raise ValueError("Кампания не найдена")
    return campaign


def _load_campaign_chats(
    session: Session,
    account_id: int,
    chat_ids: list[int],
) -> list[Chat]:
    unique_ids = sorted({int(chat_id) for chat_id in chat_ids})
    if not unique_ids:
        return []
    chats = session.query(Chat).filter(
        Chat.id.in_(unique_ids),
        Chat.advertising_account_id == account_id,
    ).all()
    if len(chats) != len(unique_ids):
        raise ValueError("Некоторые чаты не найдены или принадлежат другому аккаунту")
    return chats


def _time_to_minutes(value: str) -> int:
    normalized = validate_time_hhmm(value)
    hours, minutes = normalized.split(":")
    return int(hours) * 60 + int(minutes)
