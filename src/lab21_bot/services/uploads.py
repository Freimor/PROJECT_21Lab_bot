from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class UploadError(RuntimeError):
    pass


async def save_product_image(
    upload_dir: str | Path,
    product_id: int,
    upload: UploadFile,
) -> str:
    content_type = (upload.content_type or "").lower()
    suffix = ALLOWED_IMAGE_TYPES.get(content_type)
    if suffix is None:
        raise UploadError("Допустимы JPEG, PNG, WebP или GIF")
    root = Path(upload_dir)
    products_dir = root / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{product_id}_{uuid.uuid4().hex[:10]}{suffix}"
    path = products_dir / filename
    data = await upload.read()
    if not data:
        raise UploadError("Пустой файл")
    if len(data) > 5 * 1024 * 1024:
        raise UploadError("Файл больше 5 МБ")
    path.write_bytes(data)
    return f"products/{filename}"
