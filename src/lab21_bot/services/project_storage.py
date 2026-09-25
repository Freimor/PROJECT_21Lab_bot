"""Private project files. The directory is not mounted as static."""

from __future__ import annotations

import uuid
from pathlib import Path

from starlette.datastructures import UploadFile

from lab21_bot.services.uploads import UploadError

PROJECT_FILE_LIMIT = 25 * 1024 * 1024

_ALLOWED_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _relative(relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not relative.strip():
        raise UploadError("Некорректный путь файла")
    return rel


def resolve_private_file(root: str | Path, relative: str) -> Path:
    rel = _relative(relative)
    base = Path(root).resolve()
    full = (base / rel).resolve()
    if not full.is_relative_to(base):
        raise UploadError("Некорректный путь файла")
    return full


def read_private_file(root: str | Path, relative: str) -> bytes:
    full = resolve_private_file(root, relative)
    if not full.is_file():
        raise UploadError("Файл не найден")
    return full.read_bytes()


def unlink_private_file(root: str | Path, relative: str) -> None:
    try:
        full = resolve_private_file(root, relative)
    except UploadError:
        return
    if full.is_file():
        full.unlink()


async def save_private_file(
    root: str | Path,
    project_id: int,
    upload: UploadFile,
) -> tuple[str, str, str, int]:
    original = Path(upload.filename or "").name.strip()
    if not original or original in {".", ".."}:
        raise UploadError("Укажите имя файла")
    suffix = Path(original).suffix.lower()
    content_type = _ALLOWED_TYPES.get(suffix)
    if content_type is None:
        raise UploadError(
            "Допустимы изображения, pdf, zip, txt, md, doc, docx, xls, xlsx, ppt, pptx"
        )
    data = await upload.read()
    if not data:
        raise UploadError("Пустой файл")
    if len(data) > PROJECT_FILE_LIMIT:
        raise UploadError("Файл больше 25 МБ")
    relative = Path("projects") / str(project_id) / f"{uuid.uuid4().hex}{suffix}"
    full = resolve_private_file(root, relative.as_posix())
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return relative.as_posix(), original[:255], content_type, len(data)
