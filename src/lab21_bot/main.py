from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import structlog
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lab21_bot.config import Settings, get_settings
from lab21_bot.db import bootstrap_database, create_engine, create_session_factory
from lab21_bot.handlers import create_router
from lab21_bot.llm.client import LLMClient
from lab21_bot.models import BotSetting
from lab21_bot.scheduler import create_scheduler
from lab21_bot.services.lifecycle import LAST_RESTART_SETTING, consume_restart_result
from lab21_bot.telegram_client import create_bot_with_failover, proxy_urls


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
    )


async def notify_restart_result(
    bot: Bot,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with factory.begin() as session:
        payload: dict[str, Any] | None = await consume_restart_result(session, settings)
        if not payload or payload.get("notified"):
            return
        actor_id = payload.get("requested_by")
        status = payload.get("status", "unknown")
        applied = str(payload.get("applied_sha", "unknown"))[:12]
        updated = "да" if payload.get("updated") else "нет"
        detail = payload.get("detail", "")
        if actor_id:
            await bot.send_message(
                int(actor_id),
                "Перезагрузка завершена.\n"
                f"Статус: {status}\n"
                f"Обновления применены: {updated}\n"
                f"Версия: {applied}\n"
                f"{detail}",
            )
        payload["notified"] = True
        setting = await session.get(BotSetting, LAST_RESTART_SETTING)
        if setting is not None:
            setting.value = payload


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await bootstrap_database(engine, factory, settings)

    bot = await create_bot_with_failover(settings)
    llm = LLMClient(settings)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(create_router(settings, factory, llm))
    scheduler = create_scheduler(bot, settings, factory)

    from lab21_bot.services.commands import clear_default_commands

    try:
        await clear_default_commands(bot)
    except Exception as exc:
        log.warning("clear_default_commands_failed", error=str(exc))
    scheduler.start()
    await notify_restart_result(bot, factory, settings)
    from lab21_bot.services.quests import refresh_open_quest_posts

    try:
        async with factory.begin() as session:
            refreshed = await refresh_open_quest_posts(bot, session, settings)
        log.info("quest_posts_refreshed", count=refreshed)
    except Exception as exc:
        log.warning("quest_posts_refresh_failed", error=str(exc))
    log.info(
        "bot_started",
        model=settings.llm_model,
        provider=settings.llm_provider,
        git_sha=settings.app_git_sha,
        telegram_proxies=len(proxy_urls(settings)),
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await llm.close()
        await bot.session.close()
        await engine.dispose()
        log.info("bot_stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
