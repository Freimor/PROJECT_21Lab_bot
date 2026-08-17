"""One-off: republish open/claimed service jobs to JOB destination."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from lab21_bot.config import get_settings
from lab21_bot.models import ServiceJob, ServiceJobStatus
from lab21_bot.services.destinations import job_destination
from lab21_bot.services.job_publish import publish_service_job


async def main() -> None:
    settings = get_settings()
    dest = job_destination(settings)
    print("dest_chat_digits", len(str(abs(dest.chat_id))) if dest else None)
    print("dest_thread", dest.thread_id if dest else None)
    if dest is None:
        raise SystemExit("job destination is not configured")

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    published = 0
    failed = 0
    try:
        async with factory() as session:
            jobs = list(
                await session.scalars(
                    select(ServiceJob)
                    .where(
                        ServiceJob.status.in_(
                            [ServiceJobStatus.OPEN, ServiceJobStatus.CLAIMED]
                        )
                    )
                    .options(selectinload(ServiceJob.customer))
                    .order_by(ServiceJob.id.asc())
                )
            )
            print("jobs", len(jobs))
            for job in jobs:
                customer = job.customer
                if customer is None:
                    print("skip", job.id, "no customer")
                    failed += 1
                    continue
                mid = await publish_service_job(bot, session, settings, job, customer)
                await session.commit()
                if mid:
                    published += 1
                    print("ok", job.id, "msg", mid)
                else:
                    failed += 1
                    print("fail", job.id)
    finally:
        await bot.session.close()
        await engine.dispose()
    print("done published", published, "failed", failed)


if __name__ == "__main__":
    asyncio.run(main())
