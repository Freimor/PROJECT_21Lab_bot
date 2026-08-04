from __future__ import annotations

import asyncio
import logging
import sys

import structlog
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from lab21_bot.config import get_settings
from lab21_bot.db import bootstrap_database, create_engine, create_session_factory
from lab21_bot.handlers import create_router
from lab21_bot.llm.client import LLMClient
from lab21_bot.scheduler import create_scheduler


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


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    await bootstrap_database(engine, factory, settings)

    bot = Bot(settings.telegram_bot_token.get_secret_value())
    llm = LLMClient(settings)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(create_router(settings, factory, llm))
    scheduler = create_scheduler(bot, settings, factory)

    await bot.set_my_commands(
        [
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="balance", description="Баланс и ранг"),
            BotCommand(command="history", description="История лабкоинов"),
            BotCommand(command="shop", description="Витрина наград"),
            BotCommand(command="transfer", description="Передать лабкоины"),
            BotCommand(command="staff", description="Служебное меню"),
            BotCommand(command="post", description="Создать пост"),
        ]
    )
    scheduler.start()
    log.info("bot_started", model=settings.llm_model, provider=settings.llm_provider)
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
