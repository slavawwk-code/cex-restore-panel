import asyncio
import logging
from datetime import datetime, timedelta
from app.database import get_session
from app.database.models import Chat
from app.config import load_settings
from app.services.sender import send_message
from app.services.campaigns import get_effective_campaign_for_chat, mark_campaign_first_send_consumed

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for scheduling and sending messages."""

    def __init__(self, check_interval_seconds: int | None = None):
        self.running = False
        self.task = None
        self.check_interval_seconds = (
            check_interval_seconds
            if check_interval_seconds is not None
            else load_settings(require_secrets=False).scheduler_interval_seconds
        )

    async def start(self):
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True
        self.task = asyncio.create_task(self._run())
        logger.info("Scheduler started")

    async def stop(self):
        """Stop the scheduler."""
        if not self.running:
            logger.warning("Scheduler not running")
            return

        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def _run(self):
        """Main scheduler loop."""
        while self.running:
            try:
                await self._check_and_send()
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)

            await asyncio.sleep(self.check_interval_seconds)

    async def _check_and_send(self):
        """
        Check all active chats and send messages if cooldown expired.
        The scheduler owns the session lifecycle and is responsible for commits.
        """
        session = get_session()
        chats_checked = 0
        chats_sent = 0
        chats_skipped = 0
        chats_errors = 0

        try:
            chats = session.query(Chat).filter(Chat.status == "active").all()
            chats_checked = len(chats)
            logger.info(f"Scheduler: Starting check cycle - {chats_checked} active chats to evaluate")

            for chat in chats:
                campaign = get_effective_campaign_for_chat(session, chat.id)
                effective_template = campaign.template if campaign and campaign.template else chat.template
                effective_interval = campaign.interval_minutes if campaign else chat.cooldown_minutes

                if not effective_template:
                    logger.debug(f"Chat {chat.id} has no assigned template, skipping")
                    chats_skipped += 1
                    continue

                if not chat.account:
                    logger.debug(f"Chat {chat.id} has no account, skipping")
                    chats_skipped += 1
                    continue

                if chat.account.status != "active":
                    logger.debug(f"Chat {chat.id} account status is {chat.account.status}, skipping")
                    chats_skipped += 1
                    continue

                now = datetime.utcnow()
                last_sent = chat.last_sent_at or (now - timedelta(minutes=effective_interval + 1))
                time_since_send = now - last_sent

                first_send_due = bool(
                    campaign
                    and campaign.first_send_at
                    and now >= campaign.first_send_at
                )

                if first_send_due or time_since_send >= timedelta(minutes=effective_interval):
                    if campaign:
                        mark_campaign_first_send_consumed(session, campaign)
                    result_tuple = await self._send_to_chat(
                        session,
                        chat,
                        template=effective_template,
                        interval_minutes=effective_interval,
                        ignore_cooldown=first_send_due,
                    )
                    if result_tuple:
                        success, skipped, error = result_tuple
                        if success:
                            chats_sent += 1
                        elif skipped:
                            chats_skipped += 1
                        elif error:
                            chats_errors += 1
                else:
                    chats_skipped += 1

        except Exception as e:
            logger.error(f"Error in scheduler check cycle: {e}", exc_info=True)

        finally:
            session.close()
            logger.info(
                f"Scheduler: Cycle complete - checked={chats_checked}, "
                f"sent={chats_sent}, skipped={chats_skipped}, errors={chats_errors}"
            )

    async def _send_to_chat(
        self,
        session,
        chat: Chat,
        template=None,
        interval_minutes: int | None = None,
        ignore_cooldown: bool = False,
    ):
        """
        Send message to a specific chat using the abstracted sender.

        The scheduler owns the session and commits after send_message completes.
        Returns (success, skipped, error) tuple for accounting.
        """
        try:
            effective_template = template or chat.template
            if not chat.account or not effective_template:
                logger.warning(f"Chat {chat.id} missing account or template, skipping")
                return (False, True, False)

            result = await send_message(
                session,
                chat.account,
                chat,
                effective_template,
                interval_minutes=interval_minutes,
                ignore_cooldown=ignore_cooldown,
            )

            # Scheduler owns the session and commits after send_message
            session.commit()

            mode = result.get("mode", "UNKNOWN")
            success = result.get("success", False)

            if mode == "SKIPPED":
                logger.debug(f"Chat {chat.id} skipped: {result.get('error_message', 'Unknown reason')}")
                return (False, True, False)
            elif success:
                logger.info(f"Chat {chat.id} sent successfully (mode={mode}, msg_id={result.get('telegram_message_id')})")
                return (True, False, False)
            else:
                logger.warning(f"Chat {chat.id} send failed: {result.get('error_message', 'Unknown error')}")
                return (False, False, True)

        except Exception as e:
            logger.error(f"Exception sending to chat {chat.id}: {e}", exc_info=True)
            try:
                session.commit()
            except Exception as commit_error:
                logger.error(f"Failed to commit after send exception for chat {chat.id}: {commit_error}")
            return (False, False, True)
