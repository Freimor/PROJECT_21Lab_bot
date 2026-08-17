import asyncio

from lab21_bot.db import get_session_factory
from lab21_bot.services.templates import list_templates


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        items = await list_templates(session)
        print("templates", len(items))
        for item in items:
            print(item.id, item.kind.value, item.body[:40])


if __name__ == "__main__":
    asyncio.run(main())
