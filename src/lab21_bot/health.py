from __future__ import annotations

import asyncio

from sqlalchemy import text

from lab21_bot.config import get_settings
from lab21_bot.db import create_engine


async def check() -> None:
    engine = create_engine(get_settings())
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

