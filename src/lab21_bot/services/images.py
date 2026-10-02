"""Normalize uploaded images so the admin UI can show them in a browser."""

from __future__ import annotations

import io

import structlog
from PIL import Image, UnidentifiedImageError

logger = structlog.get_logger(__name__)

_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif"}
_JPEG_QUALITY = 85


def sniffed_image_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in _HEIF_BRANDS:
        return "image/heif"
    return None


def prepare_browser_image(content: bytes, content_type: str) -> tuple[bytes, str]:
    """Return JPEG bytes for HEIC/HEIF and the real type when Telegram mislabels the file."""
    sniffed = sniffed_image_type(content)
    if sniffed == "image/heif":
        converted = _heif_to_jpeg(content)
        if converted is not None:
            return converted, "image/jpeg"
        return content, "image/heif"
    if sniffed:
        return content, sniffed
    return content, content_type or "application/octet-stream"


def _heif_to_jpeg(content: bytes) -> bytes | None:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        logger.warning("pillow_heif_missing")
        return None
    register_heif_opener()
    try:
        with Image.open(io.BytesIO(content)) as image:
            rgb = image.convert("RGB")
            output = io.BytesIO()
            rgb.save(output, format="JPEG", quality=_JPEG_QUALITY)
            return output.getvalue()
    except (OSError, UnidentifiedImageError, ValueError):
        logger.info("heif_convert_failed")
        return None
