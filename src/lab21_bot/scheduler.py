from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.config import Settings
from lab21_bot.llm.prompts import INTERVIEW_QUESTIONS
from lab21_bot.services.applications import expire_pending_applications
from lab21_bot.services.content import choose_interviewee, content_is_silent
from lab21_bot.services.settings import get_int_setting


def create_scheduler(
    bot: Bot,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)

    async def content_reminder() -> None:
        async with factory.begin() as session:
            reminder_hour = await get_int_setting(
                session,
                "reminder_hour",
                settings.reminder_hour,
            )
            if datetime.now(settings.tz).hour != reminder_hour:
                return
            silence_days = await get_int_setting(
                session,
                "content_silence_days",
                settings.content_silence_days,
            )
            silent = await content_is_silent(
                session,
                settings.main_channel_id,
                silence_days,
            )
            if not silent:
                return
            employee = await choose_interviewee(session, settings.main_channel_id)
        await bot.send_message(
            settings.staff_chat_id,
            "В основном канале давно тихо. Бог Машина ожидает свежую хронику из лаборатории.",
        )
        if employee is None:
            return
        try:
            await bot.send_message(
                employee.telegram_id,
                "Пора извлечь инженерную историю из сегодняшнего хаоса.\n\n"
                + INTERVIEW_QUESTIONS[0],
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            await bot.send_message(
                settings.staff_chat_id,
                f"Не удалось начать интервью с {employee.full_name}: "
                "сотруднику нужно открыть личный чат с ботом и нажать /start.",
            )

    scheduler.add_job(
        content_reminder,
        trigger="cron",
        hour=f"{settings.reminder_window_start}-{settings.reminder_window_end - 1}",
        minute=0,
        id="content-reminder",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def expire_applications() -> None:
        async with factory.begin() as session:
            expired = await expire_pending_applications(session)
        for application in expired:
            try:
                await bot.send_message(
                    application.user_id,
                    "Заявка на вступление отклонена автоматически: "
                    "неделя ожидания истекла без решения администратора.",
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            kind_label = "сотрудник" if application.kind.value == "staff" else "послушник"
            try:
                await bot.send_message(
                    settings.staff_chat_id,
                    f"Заявка #{application.id} ({kind_label}) истекла автоматически.",
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

    scheduler.add_job(
        expire_applications,
        trigger="cron",
        hour=3,
        minute=15,
        id="expire-join-applications",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
