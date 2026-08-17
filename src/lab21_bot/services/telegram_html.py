"""Normalize LLM output into Telegram HTML."""

from __future__ import annotations

import html
import re

_FENCE_RE = re.compile(r"```(?:([\w+-]+)\r?\n)?(.*?)```", re.DOTALL)
_STRAY_GT_LINE = re.compile(r"(?m)^[ \t]*>[ \t]*\r?$")
_MD_QUOTE_LINE = re.compile(r"(?m)^>[ \t]?(.*)$")


def _escape_pre_body(raw: str) -> str:
    return html.escape(raw.strip("\n"))


def convert_markdown_fences(text: str) -> str:
    """Turn ``` / ```lang fences into <pre>…</pre> (Telegram HTML)."""

    def repl(match: re.Match[str]) -> str:
        body = match.group(2) or ""
        return f"<pre>{_escape_pre_body(body)}</pre>"

    return _FENCE_RE.sub(repl, text)


def strip_stray_blockquote_markers(text: str) -> str:
    """Remove lone '>' lines left by markdown/HTML hybrids."""
    cleaned = _STRAY_GT_LINE.sub("", text)
    # Collapse 3+ blank lines after removals
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def convert_markdown_quotes(text: str) -> str:
    """Convert remaining markdown `> quote` lines into <blockquote>."""
    if "<blockquote" in text.lower():
        # Already using HTML quotes — only strip stray markers
        return text
    lines = text.splitlines()
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        inner = "\n".join(buf).strip()
        out.append(f"<blockquote>{html.escape(inner)}</blockquote>")
        buf = []

    for line in lines:
        md = _MD_QUOTE_LINE.match(line)
        if md and "<" not in line:
            buf.append(md.group(1))
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


def normalize_telegram_html(text: str) -> str:
    """Best-effort cleanup of LLM output for Telegram HTML parse mode."""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    cleaned = convert_markdown_fences(cleaned)
    cleaned = strip_stray_blockquote_markers(cleaned)
    cleaned = convert_markdown_quotes(cleaned)
    cleaned = strip_stray_blockquote_markers(cleaned)
    return cleaned.strip()
