from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from lab21_bot.services.uploads import UploadError, read_uploaded_file
from lab21_bot.telegram_client import TELEGRAM_API, telegram_request

logger = structlog.get_logger(__name__)


async def notify_telegram_user(
    bot_token: str,
    telegram_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
) -> bool:
    try:
        payload: dict[str, Any] = {"chat_id": telegram_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        response = await telegram_request(
            "post",
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            request_timeout=20.0,
            json=payload,
        )
        result: dict[str, Any] = response.json()
        if not result.get("ok"):
            logger.info(
                "telegram_notify_failed",
                user_id=telegram_id,
                error=result.get("description"),
            )
            return False
        return True
    except Exception as exc:
        logger.info("telegram_notify_failed", user_id=telegram_id, error=str(exc))
        return False


class TelegramSendError(RuntimeError):
    pass


def _thread_fields(message_thread_id: int | None) -> dict[str, int]:
    if message_thread_id is None:
        return {}
    return {"message_thread_id": message_thread_id}


def _parse_mode_fields(parse_mode: str | None) -> dict[str, str]:
    if not parse_mode:
        return {}
    return {"parse_mode": parse_mode}


def _single_media_method(media_type: str) -> tuple[str, str]:
    method = {
        "photo": "sendPhoto",
        "animation": "sendAnimation",
        "video": "sendVideo",
        "document": "sendDocument",
    }.get(media_type, "sendDocument")
    field = {
        "sendPhoto": "photo",
        "sendAnimation": "animation",
        "sendVideo": "video",
        "sendDocument": "document",
    }[method]
    return method, field


def _album_media_type(media_type: str) -> str:
    # Albums: Telegram media groups don't reliably mix animations — send GIFs
    # as documents so the group stays valid (same as handlers._publish_item).
    if media_type == "photo":
        return "photo"
    if media_type == "video":
        return "video"
    return "document"


async def _attach_upload(
    upload_dir: str | Path,
    relative: str,
    attach_name: str,
    files: dict[str, tuple[str, bytes, str]],
) -> str:
    try:
        content, content_type = read_uploaded_file(upload_dir, relative)
    except UploadError as exc:
        raise TelegramSendError(str(exc)) from exc
    files[attach_name] = (Path(relative).name, content, content_type)
    return f"attach://{attach_name}"


async def _send_single_media(
    bot_token: str,
    chat_id: int,
    text: str,
    item: dict[str, Any],
    *,
    message_thread_id: int | None,
    parse_mode: str | None,
    upload_dir: str | Path | None,
) -> int:
    thread = _thread_fields(message_thread_id)
    mode = _parse_mode_fields(parse_mode)
    caption = text if len(text) <= 1024 else None
    method, field = _single_media_method(str(item.get("type", "")))
    form: dict[str, Any] = {
        "chat_id": chat_id,
        **thread,
        **({"caption": caption, **mode} if caption else {}),
    }
    file_id = item.get("file_id")
    files = None
    if file_id:
        form[field] = file_id
    else:
        relative = item.get("path")
        if not isinstance(relative, str) or not relative.strip() or upload_dir is None:
            raise TelegramSendError("У медиа нет файла")
        try:
            content, content_type = read_uploaded_file(upload_dir, relative)
        except UploadError as exc:
            raise TelegramSendError(str(exc)) from exc
        files = {field: (Path(relative).name, content, content_type)}
    response = await telegram_request(
        "post",
        f"{TELEGRAM_API}/bot{bot_token}/{method}",
        request_timeout=40.0,
        data=form if files is not None else None,
        json=None if files is not None else form,
        files=files,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise TelegramSendError(str(payload.get("description", "send failed")))
    message_id = int(payload["result"]["message_id"])
    if caption is None and text.strip():
        follow = await telegram_request(
            "post",
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            request_timeout=40.0,
            json={"chat_id": chat_id, "text": text, **thread, **mode},
        )
        follow_payload = follow.json()
        if follow_payload.get("ok"):
            message_id = int(follow_payload["result"]["message_id"])
    return message_id


async def _send_media_group(
    bot_token: str,
    chat_id: int,
    text: str,
    items: list[dict[str, Any]],
    *,
    message_thread_id: int | None,
    parse_mode: str | None,
    upload_dir: str | Path | None,
) -> int:
    thread = _thread_fields(message_thread_id)
    mode = _parse_mode_fields(parse_mode)
    caption = text if len(text) <= 1024 else None
    media_payload: list[dict[str, Any]] = []
    files: dict[str, tuple[str, bytes, str]] = {}
    for index, item in enumerate(items):
        entry: dict[str, Any] = {"type": _album_media_type(str(item.get("type", "")))}
        if index == 0 and caption is not None:
            entry["caption"] = caption
            entry.update(mode)
        file_id = item.get("file_id")
        if file_id:
            entry["media"] = file_id
        else:
            relative = item.get("path")
            if not isinstance(relative, str) or not relative.strip() or upload_dir is None:
                raise TelegramSendError("У медиа нет файла")
            attach_name = f"file{index}"
            entry["media"] = await _attach_upload(upload_dir, relative, attach_name, files)
        media_payload.append(entry)

    form: dict[str, Any] = {
        "chat_id": str(chat_id),
        "media": json.dumps(media_payload, ensure_ascii=False),
        **{key: str(value) for key, value in thread.items()},
    }
    response = await telegram_request(
        "post",
        f"{TELEGRAM_API}/bot{bot_token}/sendMediaGroup",
        request_timeout=60.0,
        data=form,
        files=files or None,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise TelegramSendError(str(payload.get("description", "send failed")))
    result = payload["result"]
    if not isinstance(result, list) or not result:
        raise TelegramSendError("empty media group response")
    message_id = int(result[0]["message_id"])
    if caption is None and text.strip():
        follow = await telegram_request(
            "post",
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            request_timeout=40.0,
            json={"chat_id": chat_id, "text": text, **thread, **mode},
        )
        follow_payload = follow.json()
        if follow_payload.get("ok"):
            message_id = int(follow_payload["result"]["message_id"])
    return message_id


async def send_telegram_message(
    bot_token: str,
    chat_id: int,
    text: str,
    *,
    media: list[dict[str, Any]] | None = None,
    message_thread_id: int | None = None,
    parse_mode: str | None = None,
    upload_dir: str | Path | None = None,
) -> int:
    """Send text and optional media (including albums) to a chat/topic; return message_id."""
    thread = _thread_fields(message_thread_id)
    mode = _parse_mode_fields(parse_mode)
    items = media or []
    if not items:
        response = await telegram_request(
            "post",
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            request_timeout=40.0,
            json={"chat_id": chat_id, "text": text, **thread, **mode},
        )
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramSendError(str(payload.get("description", "send failed")))
        return int(payload["result"]["message_id"])

    if len(items) == 1:
        return await _send_single_media(
            bot_token,
            chat_id,
            text,
            items[0],
            message_thread_id=message_thread_id,
            parse_mode=parse_mode,
            upload_dir=upload_dir,
        )

    return await _send_media_group(
        bot_token,
        chat_id,
        text,
        items,
        message_thread_id=message_thread_id,
        parse_mode=parse_mode,
        upload_dir=upload_dir,
    )
