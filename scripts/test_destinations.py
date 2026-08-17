import asyncio

import httpx

from lab21_bot.config import get_settings
from lab21_bot.models import ContentKind
from lab21_bot.services.destinations import destination_for_kind, flood_destination, shop_destination
from lab21_bot.services.notify import TelegramSendError, send_telegram_message


async def main() -> None:
    settings = get_settings()
    token = settings.telegram_bot_token.get_secret_value()
    async with httpx.AsyncClient(timeout=30.0) as client:
        for label, chat_id in (
            ("forum", settings.main_channel_id),
            ("staff", settings.staff_chat_id),
        ):
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getChat",
                params={"chat_id": chat_id},
            )
            payload = response.json()
            if payload.get("ok"):
                title = payload["result"].get("title") or payload["result"].get("type")
                print(f"getChat OK {label}: {title} ({chat_id})")
            else:
                print(f"getChat FAIL {label}: {chat_id} -> {payload.get('description')}")

    staff = type("D", (), {"chat_id": settings.staff_chat_id, "thread_id": None})()
    targets = [
        ("Budni", destination_for_kind(settings, ContentKind.STORY)),
        ("Vazhnoe", destination_for_kind(settings, ContentKind.IMPORTANT)),
        ("Flood", flood_destination(settings)),
        ("Shop", shop_destination(settings)),
        ("Staff", staff),
    ]
    for name, dest in targets:
        if dest is None:
            print(f"SKIP {name}")
            continue
        text = (
            f"[Lab21 test] {name}\n"
            f"chat={dest.chat_id} thread={dest.thread_id}"
        )
        try:
            message_id = await send_telegram_message(
                token,
                dest.chat_id,
                text,
                message_thread_id=dest.thread_id,
            )
            print(f"OK {name}: message_id={message_id} thread={dest.thread_id}")
        except TelegramSendError as error:
            print(f"FAIL {name}: thread={dest.thread_id} -> {error}")


if __name__ == "__main__":
    asyncio.run(main())
