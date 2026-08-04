from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.config import Settings
from lab21_bot.llm.prompts import INTERVIEW_QUESTIONS
from lab21_bot.services.content import choose_interviewee, content_is_silent


def create_scheduler(
    bot: Bot,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)

    async def content_reminder() -> None:
        async with factory.begin() as session:
            silent = await content_is_silent(
                session,
                settings.main_channel_id,
                settings.content_silence_days,
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
        hour=settings.reminder_hour,
        minute=0,
        id="content-reminder",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler

