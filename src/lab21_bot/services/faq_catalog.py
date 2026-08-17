"""FAQ markdown catalog shared by admin routes and nav."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

FAQ_DIR = Path(__file__).resolve().parents[1] / "data" / "faq"
_SLUG_RE = re.compile(r"^\d+-([a-z0-9-]+)$", re.I)


@cache
def list_faq_pages() -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    if not FAQ_DIR.is_dir():
        return pages
    for path in sorted(FAQ_DIR.glob("*.md")):
        stem = path.stem
        match = _SLUG_RE.match(stem)
        slug = match.group(1) if match else stem
        text = path.read_text(encoding="utf-8")
        title = stem
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        pages.append(
            {
                "slug": slug,
                "stem": stem,
                "title": title,
                "path": str(path),
            }
        )
    return pages


def faq_page_by_slug(slug: str) -> dict[str, str] | None:
    for page in list_faq_pages():
        if page["slug"] == slug or page["stem"] == slug:
            return page
    return None
