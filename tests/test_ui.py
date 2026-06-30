import unittest

from app.keyboards.main import get_main_menu
from app.keyboards.proxy import (
    get_proxy_confirmation_keyboard,
    get_proxy_detection_confirmation_keyboard,
    get_proxy_menu_keyboard,
    get_proxy_saved_keyboard,
    get_proxy_setup_method_keyboard,
)
from app.services.telethon_auth import _describe_delivery


class MainMenuTests(unittest.TestCase):
    def test_main_menu_is_symmetric_four_by_two_grid(self):
        keyboard = get_main_menu()
        self.assertEqual([len(row) for row in keyboard.inline_keyboard], [2, 2, 2, 2])
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Аккаунты", labels)
        self.assertIn("Настройки", labels)
        self.assertFalse(any(label[0] in "📊💬📝📢📋✅👥⚙️" for label in labels))


class ProxyKeyboardTests(unittest.TestCase):
    def test_enabled_proxy_menu_has_fast_and_full_checks(self):
        labels = [
            row[0].text for row in get_proxy_menu_keyboard(7, True).inline_keyboard
        ]
        self.assertEqual(
            labels,
            [
                "Быстрая проверка",
                "Полная диагностика",
                "История",
                "Изменить",
                "Отключить",
                "Назад",
            ],
        )

    def test_paste_mode_is_the_recommended_first_choice(self):
        keyboard = get_proxy_setup_method_keyboard(7)
        self.assertEqual(
            keyboard.inline_keyboard[0][0].text,
            "Вставить строкой (рекомендуется)",
        )
        self.assertEqual(
            keyboard.inline_keyboard[1][0].text, "Заполнить вручную"
        )

    def test_confirmation_allows_save_edit_and_cancel(self):
        labels = [
            row[0].text for row in get_proxy_confirmation_keyboard(7).inline_keyboard
        ]
        self.assertEqual(labels, ["Сохранить", "Изменить", "Отмена"])

    def test_auto_detection_confirmation_saves_and_tests(self):
        labels = [
            row[0].text
            for row in get_proxy_detection_confirmation_keyboard(7).inline_keyboard
        ]
        self.assertEqual(
            labels,
            ["Сохранить и проверить", "Изменить", "Отмена"],
        )

    def test_saved_proxy_offers_immediate_test(self):
        labels = [row[0].text for row in get_proxy_saved_keyboard(7).inline_keyboard]
        self.assertEqual(labels, ["Проверить", "Позже"])


class LoginCodeDeliveryTests(unittest.TestCase):
    def test_app_delivery_is_explained_in_russian(self):
        sent_code_type = type("SentCodeTypeApp", (), {})()
        sent_code = type("SentCode", (), {"type": sent_code_type})()
        self.assertEqual(
            _describe_delivery(sent_code), "в официальное приложение Telegram"
        )


if __name__ == "__main__":
    unittest.main()
