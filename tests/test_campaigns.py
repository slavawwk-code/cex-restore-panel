import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import AdvertisingAccount, Base, Campaign, Chat, Template
from app.keyboards.campaigns import get_campaign_edit_keyboard, get_campaign_first_send_keyboard
from app.scheduler.service import SchedulerService
from app.services.campaigns import (
    create_campaign,
    format_campaign_send_summary,
    get_effective_campaign_for_chat,
    is_campaign_inside_schedule,
    parse_schedule_window,
    rename_campaign,
    run_campaign_once,
    schedule_campaign_first_send,
    set_campaign_chats,
    update_campaign_interval,
    update_campaign_schedule,
    update_campaign_template,
)


class CampaignEditTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.account = AdvertisingAccount(
            display_name="Main",
            phone_number="+70000000001",
            telethon_session="main",
            status="active",
            session_connected=True,
        )
        self.template_one = Template(name="One", text="first", is_active=True)
        self.template_two = Template(name="Two", text="second", is_active=True)
        self.session.add_all([self.account, self.template_one, self.template_two])
        self.session.commit()
        self.chat_one = Chat(
            advertising_account_id=self.account.id,
            title="Chat One",
            username_or_chat_id="@one",
            cooldown_minutes=60,
            assigned_template_id=self.template_one.id,
            last_sent_at=datetime.utcnow() - timedelta(minutes=20),
        )
        self.chat_two = Chat(
            advertising_account_id=self.account.id,
            title="Chat Two",
            username_or_chat_id="@two",
            cooldown_minutes=60,
            assigned_template_id=self.template_one.id,
            last_sent_at=datetime.utcnow() - timedelta(minutes=20),
        )
        self.session.add_all([self.chat_one, self.chat_two])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_campaign_edit_menu_has_required_actions(self):
        keyboard = get_campaign_edit_keyboard(42)
        labels = [row[0].text for row in keyboard.inline_keyboard]

        self.assertEqual(
            labels,
            [
                "Change template",
                "Change interval",
                "Manage chats",
                "Rename campaign",
                "Configure schedule",
                "Тестовая отправка сейчас",
                "Back",
            ],
        )

    def test_campaign_setup_first_send_prompt_has_required_actions(self):
        keyboard = get_campaign_first_send_keyboard(42)
        labels = [row[0].text for row in keyboard.inline_keyboard]

        self.assertEqual(
            labels,
            [
                "Отправить сейчас",
                "Через 5 минут",
                "По обычному интервалу",
                "Назад",
            ],
        )

    def test_campaign_updates_in_place_and_preserves_binding_and_chats(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_one.id,
            interval_minutes=60,
            chat_ids=[self.chat_one.id],
        )
        campaign_id = campaign.id

        update_campaign_template(self.session, campaign_id, self.template_two.id)
        update_campaign_interval(self.session, campaign_id, 15)
        rename_campaign(self.session, campaign_id, "Launch RC")
        update_campaign_schedule(self.session, campaign_id, enabled=False)
        self.session.expire_all()

        updated = self.session.query(Campaign).filter(Campaign.id == campaign_id).one()
        self.assertEqual(updated.id, campaign_id)
        self.assertEqual(updated.account_id, self.account.id)
        self.assertEqual(updated.template_id, self.template_two.id)
        self.assertEqual(updated.interval_minutes, 15)
        self.assertEqual(updated.name, "Launch RC")
        self.assertFalse(updated.schedule_enabled)
        self.assertEqual([chat.id for chat in updated.chats], [self.chat_one.id])

    def test_manage_chats_preserves_until_explicit_save(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_one.id,
            chat_ids=[self.chat_one.id],
        )
        campaign_id = campaign.id

        self.session.expire_all()
        before = self.session.query(Campaign).filter(Campaign.id == campaign_id).one()
        self.assertEqual([chat.id for chat in before.chats], [self.chat_one.id])

        set_campaign_chats(self.session, campaign_id, [self.chat_one.id, self.chat_two.id])
        self.session.expire_all()
        after = self.session.query(Campaign).filter(Campaign.id == campaign_id).one()
        self.assertEqual({chat.id for chat in after.chats}, {self.chat_one.id, self.chat_two.id})

    def test_effective_campaign_returns_active_scheduled_assignment(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            interval_minutes=15,
            chat_ids=[self.chat_one.id],
        )

        effective = get_effective_campaign_for_chat(self.session, self.chat_one.id)
        self.assertEqual(effective.id, campaign.id)
        self.assertEqual(effective.template_id, self.template_two.id)
        self.assertEqual(effective.interval_minutes, 15)

    def test_schedule_window_is_validated_and_enforced(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            interval_minutes=15,
            chat_ids=[self.chat_one.id],
        )
        start_time, end_time = parse_schedule_window("09:00-18:00")
        update_campaign_schedule(
            self.session,
            campaign.id,
            enabled=True,
            start_time=start_time,
            end_time=end_time,
        )
        self.session.refresh(campaign)

        self.assertTrue(is_campaign_inside_schedule(campaign, datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(is_campaign_inside_schedule(campaign, datetime(2026, 1, 1, 20, 0)))

    def test_scheduler_uses_campaign_template_and_interval(self):
        create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            interval_minutes=15,
            chat_ids=[self.chat_one.id],
        )
        template_two_id = self.template_two.id
        self.session.close()

        captured = {}

        async def fake_send_message(
            session,
            account,
            chat,
            template,
            interval_minutes=None,
            ignore_cooldown=False,
        ):
            captured["template_id"] = template.id
            captured["interval_minutes"] = interval_minutes
            captured["ignore_cooldown"] = ignore_cooldown
            return {
                "success": True,
                "mode": "SIMULATION",
                "account_id": account.id,
                "chat_id": chat.id,
                "template_id": template.id,
                "telegram_message_id": None,
                "error_message": None,
            }

        scheduler = SchedulerService(check_interval_seconds=1)
        with patch("app.scheduler.service.get_session", self.Session):
            with patch("app.scheduler.service.send_message", fake_send_message):
                asyncio.run(scheduler._check_and_send())

        self.assertEqual(captured["template_id"], template_two_id)
        self.assertEqual(captured["interval_minutes"], 15)

    def test_send_now_triggers_one_send_cycle_only_and_keeps_interval(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            interval_minutes=37,
            chat_ids=[self.chat_one.id],
        )
        campaign_id = campaign.id
        calls = []

        async def fake_send_message(
            session,
            account,
            chat,
            template,
            interval_minutes=None,
            ignore_cooldown=False,
        ):
            calls.append((chat.id, template.id, interval_minutes, ignore_cooldown))
            return {
                "success": True,
                "mode": "SIMULATION",
                "account_id": account.id,
                "chat_id": chat.id,
                "template_id": template.id,
                "telegram_message_id": None,
                "error_message": None,
            }

        with patch("app.services.campaigns.send_message", fake_send_message):
            summary = asyncio.run(run_campaign_once(self.session, campaign_id))

        self.session.expire_all()
        updated = self.session.query(Campaign).filter(Campaign.id == campaign_id).one()
        self.assertEqual(summary.sent_count, 1)
        self.assertEqual(summary.skipped_count, 0)
        self.assertEqual(summary.errors_count, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], 37)
        self.assertTrue(calls[0][3])
        self.assertEqual(updated.interval_minutes, 37)

    def test_send_now_respects_dry_run_sender_result(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            chat_ids=[self.chat_one.id],
        )

        async def fake_send_message(*args, **kwargs):
            return {
                "success": True,
                "mode": "SIMULATION",
                "account_id": self.account.id,
                "chat_id": self.chat_one.id,
                "template_id": self.template_two.id,
                "telegram_message_id": None,
                "error_message": None,
            }

        with patch("app.services.campaigns.send_message", fake_send_message):
            summary = asyncio.run(run_campaign_once(self.session, campaign.id))

        self.assertEqual(summary.sent_count, 1)
        self.assertIn("Отправлено: 1", format_campaign_send_summary(summary))

    def test_no_chats_returns_clear_skip_reason(self):
        campaign = create_campaign(
            self.session,
            "Empty",
            self.account.id,
            self.template_two.id,
            chat_ids=[],
        )

        summary = asyncio.run(run_campaign_once(self.session, campaign.id))

        self.assertEqual(summary.sent_count, 0)
        self.assertEqual(summary.skipped_count, 1)
        self.assertIn("Нет активных чатов", summary.reasons)

    def test_no_template_returns_clear_skip_reason(self):
        campaign = create_campaign(
            self.session,
            "No Template",
            self.account.id,
            None,
            chat_ids=[self.chat_one.id],
        )

        summary = asyncio.run(run_campaign_once(self.session, campaign.id))

        self.assertEqual(summary.sent_count, 0)
        self.assertEqual(summary.skipped_count, 1)
        self.assertIn("Нет активного шаблона", summary.reasons)

    def test_disabled_account_blocks_manual_send(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            chat_ids=[self.chat_one.id],
        )
        self.account.status = "disabled"
        self.session.commit()

        summary = asyncio.run(run_campaign_once(self.session, campaign.id))

        self.assertEqual(summary.sent_count, 0)
        self.assertEqual(summary.skipped_count, 1)
        self.assertIn("Аккаунт не активен", summary.reasons)

    def test_first_send_after_five_minutes_keeps_regular_interval(self):
        campaign = create_campaign(
            self.session,
            "Launch",
            self.account.id,
            self.template_two.id,
            interval_minutes=41,
            chat_ids=[self.chat_one.id],
        )

        schedule_campaign_first_send(self.session, campaign.id, 5)
        self.session.refresh(campaign)

        self.assertIsNotNone(campaign.first_send_at)
        self.assertEqual(campaign.interval_minutes, 41)


if __name__ == "__main__":
    unittest.main()
