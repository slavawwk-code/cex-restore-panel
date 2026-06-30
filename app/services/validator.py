import logging
from sqlalchemy.orm import Session
from app.database.models import AdvertisingAccount, Chat, Template

logger = logging.getLogger(__name__)


class ValidationIssue:
    """Represents a single validation issue."""

    def __init__(self, severity: str, entity_type: str, entity_name: str, issue: str, details: dict = None):
        self.severity = severity  # error, warning, ok
        self.entity_type = entity_type  # account, chat, template, session
        self.entity_name = entity_name
        self.issue = issue
        self.details = details or {}

    def __repr__(self):
        return f"<ValidationIssue {self.severity} - {self.entity_type} '{self.entity_name}': {self.issue}>"


class CampaignValidator:
    """Validates the entire campaign configuration."""

    def __init__(self, session: Session):
        self.session = session
        self.issues = []
        self.accounts_checked = 0
        self.chats_checked = 0
        self.templates_checked = 0

    def validate_campaign(self) -> dict:
        """Validate entire campaign."""
        self.issues = []

        self.validate_accounts()
        self.validate_templates()
        self.validate_chats()
        self.validate_sessions()

        return self.get_summary()

    def validate_accounts(self):
        """Validate all advertising accounts."""
        accounts = self.session.query(AdvertisingAccount).all()

        for account in accounts:
            self.accounts_checked += 1

            # Check if active
            if account.status == "disabled":
                self.issues.append(
                    ValidationIssue("error", "account", account.display_name, "Аккаунт отключён")
                )
                continue

            # Check if has chats
            if not account.chats:
                self.issues.append(
                    ValidationIssue("warning", "account", account.display_name, "Нет назначенных чатов")
                )

            if not self.issues or self.issues[-1].entity_name != account.display_name:
                self.issues.append(
                    ValidationIssue("ok", "account", account.display_name, "OK")
                )

    def validate_templates(self):
        """Validate all templates."""
        templates = self.session.query(Template).all()

        for template in templates:
            self.templates_checked += 1

            if not template.is_active:
                # Check if any chat uses this template
                chats_using = self.session.query(Chat).filter(Chat.assigned_template_id == template.id).count()
                if chats_using > 0:
                    self.issues.append(
                        ValidationIssue(
                            "error",
                            "template",
                            template.name,
                            f"Шаблон отключён, но используется в чатах: {chats_using}",
                        )
                    )
                continue

            # Template is active - ok
            self.issues.append(
                ValidationIssue("ok", "template", template.name, "OK")
            )

    def validate_chats(self):
        """Validate all chats."""
        chats = self.session.query(Chat).filter(Chat.is_active.is_(True)).all()

        for chat in chats:
            self.chats_checked += 1
            issues_for_chat = []

            # Check account
            if not chat.account:
                issues_for_chat.append("Аккаунт не найден")
            elif chat.account.status == "disabled":
                issues_for_chat.append("Аккаунт отключён")
            elif chat.account.status != "active":
                status_label = {
                    "paused": "на паузе",
                    "warming": "на прогреве",
                    "disabled": "отключён",
                }.get(chat.account.status, "неактивен")
                issues_for_chat.append(f"Аккаунт {status_label}")

            # Check template
            if not chat.assigned_template_id:
                issues_for_chat.append("Шаблон не назначен")
            elif not chat.template:
                issues_for_chat.append("Назначенный шаблон не найден")
            elif not chat.template.is_active:
                issues_for_chat.append("Назначенный шаблон отключён")

            # Check cooldown
            if chat.cooldown_minutes < 1:
                issues_for_chat.append("Интервал меньше 1 минуты")
            elif chat.cooldown_minutes > 1440:
                issues_for_chat.append("Интервал больше 1440 минут")

            # Check username/id
            if not chat.username_or_chat_id:
                issues_for_chat.append("Не указан username или ID чата")

            if issues_for_chat:
                for issue in issues_for_chat:
                    self.issues.append(
                        ValidationIssue("error", "chat", chat.title, issue)
                    )
            else:
                if chat.status == "paused":
                    self.issues.append(
                        ValidationIssue("warning", "chat", chat.title, "Чат приостановлен")
                    )
                elif chat.status == "error":
                    self.issues.append(
                        ValidationIssue("warning", "chat", chat.title, "Чат находится в состоянии ошибки")
                    )
                else:
                    self.issues.append(
                        ValidationIssue("ok", "chat", chat.title, "OK")
                    )

    def validate_sessions(self):
        """Validate all account sessions."""
        accounts = self.session.query(AdvertisingAccount).filter(AdvertisingAccount.status == "active").all()

        for account in accounts:
            if not account.session_connected:
                self.issues.append(
                    ValidationIssue("error", "session", account.display_name, "Сессия не подключена")
                )

    def get_summary(self) -> dict:
        """Get validation summary."""
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]
        ok = [i for i in self.issues if i.severity == "ok"]

        return {
            "accounts_checked": self.accounts_checked,
            "chats_checked": self.chats_checked,
            "templates_checked": self.templates_checked,
            "errors": errors,
            "warnings": warnings,
            "ok_items": ok,
            "total_issues": len(errors),
            "is_valid": len(errors) == 0,
        }

    def format_issues(self) -> str:
        """Format issues for display."""
        if not self.issues:
            return "Проблем не найдено."

        text = ""
        by_type = {}

        for issue in self.issues:
            key = f"{issue.entity_type}_{issue.entity_name}"
            if key not in by_type:
                by_type[key] = []
            by_type[key].append(issue)

        for key, type_issues in by_type.items():
            first = type_issues[0]

            if first.severity == "error":
                emoji = "❌"
            elif first.severity == "warning":
                emoji = "⚠️"
            else:
                emoji = "✅"

            entity_label = {
                "account": "Аккаунт",
                "chat": "Чат",
                "template": "Шаблон",
                "session": "Сессия",
            }.get(first.entity_type, first.entity_type)
            text += f"{emoji} {entity_label} «{first.entity_name}»\n"

            for issue in type_issues:
                if issue.severity != "ok":
                    text += f"  {issue.issue}\n"

            text += "\n"

        return text
