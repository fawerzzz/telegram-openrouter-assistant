from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database, Reminder


logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bot: Bot, db: Database, timezone_name: str) -> None:
        self.bot = bot
        self.db = db
        self.timezone = ZoneInfo(timezone_name)
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)

    async def start(self) -> None:
        # Интервальная проверка страхует от пропущенных date job после перезапуска.
        self.scheduler.add_job(
            self.send_due_reminders,
            "interval",
            seconds=30,
            id="due_reminders_check",
            replace_existing=True,
        )
        for reminder in await self.db.get_pending_reminders():
            await self.schedule_reminder(reminder)
        self.scheduler.start()

    async def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    async def schedule_reminder(self, reminder: Reminder) -> None:
        trigger_time = datetime.fromisoformat(reminder.trigger_time)
        if trigger_time.tzinfo is None:
            trigger_time = trigger_time.replace(tzinfo=self.timezone)

        if trigger_time <= datetime.now(self.timezone):
            await self.send_reminder(reminder)
            return

        self.scheduler.add_job(
            self.send_reminder,
            "date",
            run_date=trigger_time,
            args=[reminder],
            id=f"reminder:{reminder.id}",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    async def send_due_reminders(self) -> None:
        for reminder in await self.db.get_due_reminders(datetime.now(self.timezone)):
            await self.send_reminder(reminder)

    async def send_reminder(self, reminder: Reminder) -> None:
        try:
            await self.bot.send_message(
                chat_id=reminder.chat_id,
                text=f"Напоминание: {reminder.reminder_text}",
                message_thread_id=reminder.thread_id or None,
            )
            await self.db.mark_reminder_sent(reminder.id)
        except Exception:
            logger.exception("Не удалось отправить напоминание %s", reminder.id)
