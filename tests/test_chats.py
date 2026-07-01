import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import AdvertisingAccount, Base, Template
from app.keyboards.chats import get_account_chats_keyboard
from app.services.chats import (
    ChatAccessCheck,
    create_chat,
    format_chat_access_error,
)


class ChatCreationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.account = AdvertisingAccount(
            display_name="Main",
            phone_number="+70000000000",
            telethon_session="main",
            status="active",
        )
        self.template = Template(name="Template", text="Hello")
        self.session.add_all([self.account, self.template])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_empty_account_chats_screen_has_action_buttons(self):
        keyboard = get_account_chats_keyboard(self.account.id)
        labels = [row[0].text for row in keyboard.inline_keyboard]
        callbacks = [row[0].callback_data for row in keyboard.inline_keyboard]

        self.assertEqual(labels, ["Добавить чат", "Назначить чаты", "Назад"])
        self.assertEqual(
            callbacks,
            [
                f"chat_create_for_account_{self.account.id}",
                f"chat_create_for_account_{self.account.id}",
                f"account_detail_{self.account.id}",
            ],
        )

    def test_chat_creation_uses_assigned_template_id_not_template_id(self):
        captured_kwargs = {}
        original_init = None

        from app.database.models import Chat

        original_init = Chat.__init__

        def capture_init(instance, **kwargs):
            captured_kwargs.update(kwargs)
            original_init(instance, **kwargs)

        with patch.object(Chat, "__init__", capture_init):
            chat = create_chat(
                self.session,
                advertising_account_id=self.account.id,
                template_id=self.template.id,
                title="Resolved title",
                username_or_chat_id="@groupname",
                cooldown_minutes=30,
            )

        self.assertNotIn("template_id", captured_kwargs)
        self.assertEqual(captured_kwargs["assigned_template_id"], self.template.id)
        self.assertEqual(chat.assigned_template_id, self.template.id)
        self.assertEqual(chat.title, "Resolved title")

    def test_successful_chat_creation_with_resolved_title(self):
        inspection = ChatAccessCheck(
            success=True,
            title="Very Nice Group",
            access_ok=True,
            can_write=True,
        )
        chat = create_chat(
            self.session,
            advertising_account_id=self.account.id,
            template_id=self.template.id,
            title=inspection.title,
            username_or_chat_id="-100123456789",
            cooldown_minutes=45,
        )

        self.assertEqual(chat.title, "Very Nice Group")
        self.assertEqual(chat.username_or_chat_id, "-100123456789")
        self.assertEqual(chat.cooldown_minutes, 45)

    def test_entity_lookup_failure_reason_is_user_facing(self):
        error = ValueError("entity not found")
        self.assertIn("ValueError", format_chat_access_error(error))
        self.assertIn("entity not found", format_chat_access_error(error))


if __name__ == "__main__":
    unittest.main()
