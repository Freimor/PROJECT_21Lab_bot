from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.config import Settings
from lab21_bot.data import setting_default
from lab21_bot.models import BotSetting, TemplateKind
from lab21_bot.services.applications import expire_pending_applications
from lab21_bot.services.content import content_is_silent, list_due_scheduled, publish_content_item
from lab21_bot.services.destinations import flood_destination
from lab21_bot.services.flood import maybe_send_flood_teaser
from lab21_bot.services.memes import meme_post_html_from_template, record_collection_meme_post
from lab21_bot.services.notify import send_telegram_message
from lab21_bot.services.settings import get_int_setting
from lab21_bot.services.templates import pick_template


def create_scheduler(
    bot: Bot,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    token = settings.telegram_bot_token.get_secret_value()

    async def content_reminder() -> None:
        """Remind staff only when Будни are silent — do not auto-interview peers."""
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
        try:
            await bot.send_message(
                settings.staff_chat_id,
                "В «Буднях лабы» давно тихо. Нужна хроника прогресса — "
                "попросите кого-то из участников или сотрудников начать пост через бота.",
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            pass

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

    async def publish_due_content() -> None:
        async with factory.begin() as session:
            due = await list_due_scheduled(session)
            for item in due:
                try:
                    published = await publish_content_item(
                        session, token, settings, item.id
                    )
                    await maybe_send_flood_teaser(
                        session,
                        token,
                        flood_destination(settings),
                        published,
                        published.author,
                        story_thread_id=settings.main_thread_id,
                    )
                except Exception:
                    continue

    scheduler.add_job(
        publish_due_content,
        trigger="interval",
        minutes=1,
        id="publish-due-content",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def flood_memes() -> None:
        flood = flood_destination(settings)
        if flood is None:
            return
        async with factory.begin() as session:
            if not await get_int_setting(
                session, "memes_enabled", setting_default("memes_enabled")
            ):
                return
            interval = await get_int_setting(
                session, "meme_interval_hours", setting_default("meme_interval_hours")
            )
            stamp = await session.get(BotSetting, "last_flood_meme_at")
            now = datetime.now(settings.tz)
            if stamp is not None:
                raw = stamp.value.get("iso")
                if isinstance(raw, str):
                    try:
                        last = datetime.fromisoformat(raw)
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=settings.tz)
                        hours = (now - last.astimezone(settings.tz)).total_seconds() / 3600
                        if hours < interval:
                            return
                    except ValueError:
                        pass
            last_id_setting = await session.get(BotSetting, "last_meme_template_id")
            exclude = None
            if last_id_setting and isinstance(last_id_setting.value.get("value"), int):
                exclude = int(last_id_setting.value["value"])
            from lab21_bot.services.seasons import active_season

            season = await active_season(session, today=now.date())
            collection = season.meme_collection if season is not None else "default"
            template = await pick_template(
                session,
                TemplateKind.MEME,
                exclude_id=exclude,
                collection_key=collection,
            )
            if template is None:
                return
            message_id = await send_telegram_message(
                token,
                flood.chat_id,
                meme_post_html_from_template(template),
                media=list(template.media or []) or None,
                message_thread_id=flood.thread_id,
                parse_mode="HTML",
            )
            await record_collection_meme_post(
                session,
                template,
                chat_id=flood.chat_id,
                message_id=message_id,
                fallback_author_id=settings.bootstrap_magister_id,
            )
            if stamp is None:
                session.add(BotSetting(key="last_flood_meme_at", value={"iso": now.isoformat()}))
            else:
                stamp.value = {"iso": now.isoformat()}
            if last_id_setting is None:
                session.add(
                    BotSetting(key="last_meme_template_id", value={"value": template.id})
                )
            else:
                last_id_setting.value = {"value": template.id}

    scheduler.add_job(
        flood_memes,
        trigger="interval",
        minutes=30,
        id="flood-memes",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def grace_bounds() -> None:
        async with factory.begin() as session:
            from lab21_bot.services.grace_refill import adjust_grace_bounds

            await adjust_grace_bounds(session)

    scheduler.add_job(
        grace_bounds,
        trigger="cron",
        hour=0,
        minute=10,
        id="daily-grace-refill",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def season_lifecycle() -> None:
        from lab21_bot.data import phrase
        from lab21_bot.services.destinations import destination_for_kind
        from lab21_bot.services.seasons import (
            format_season_announce,
            seasons_needing_end_announce,
            seasons_needing_reminder,
            seasons_needing_start_announce,
        )
        from lab21_bot.models import ContentKind

        today = datetime.now(settings.tz).date()
        async with factory.begin() as session:
            reminder_days = await get_int_setting(
                session, "season_reminder_days", setting_default("season_reminder_days")
            )
            reminders = await seasons_needing_reminder(
                session, today=today, days_before=reminder_days
            )
            starts = await seasons_needing_start_announce(session, today=today)
            ends = await seasons_needing_end_announce(session, today=today)

        for season in reminders:
            try:
                await bot.send_message(
                    settings.staff_chat_id,
                    phrase(
                        "seasons",
                        "reminder",
                        title=season.title,
                        days=reminder_days,
                        starts_on=season.starts_on.isoformat(),
                    ),
                )
                async with factory.begin() as session:
                    row = await session.get(type(season), season.id)
                    if row is not None:
                        row.reminder_sent = True
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

        try:
            dest = destination_for_kind(settings, ContentKind.IMPORTANT)
        except Exception:
            dest = None

        for season in starts:
            if dest is not None:
                thread_kwargs = (
                    {"message_thread_id": dest.thread_id}
                    if dest.thread_id is not None
                    else {}
                )
                try:
                    await bot.send_message(
                        dest.chat_id,
                        format_season_announce(season, "start"),
                        **thread_kwargs,
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
            async with factory.begin() as session:
                row = await session.get(type(season), season.id)
                if row is not None:
                    row.start_announced = True

        for season in ends:
            if dest is not None:
                thread_kwargs = (
                    {"message_thread_id": dest.thread_id}
                    if dest.thread_id is not None
                    else {}
                )
                try:
                    await bot.send_message(
                        dest.chat_id,
                        format_season_announce(season, "end"),
                        **thread_kwargs,
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
            async with factory.begin() as session:
                row = await session.get(type(season), season.id)
                if row is not None:
                    row.end_announced = True

    scheduler.add_job(
        season_lifecycle,
        trigger="cron",
        hour=9,
        minute=5,
        id="season-lifecycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
