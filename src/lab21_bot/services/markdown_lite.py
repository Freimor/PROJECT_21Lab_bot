"""Minimal Markdown → HTML for admin FAQ pages."""

from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_UL_ITEM = re.compile(r"^[-*]\s+(.*)$")
_OL_ITEM = re.compile(r"^(\d+)\.\s+(.*)$")
_CODE_FENCE = re.compile(r"^```")
_TABLE_ROW = re.compile(r"^\|.+\|\s*$")
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|\s*$")


def _inline_format(text: str) -> str:
    parts: list[str] = []
    i = 0
    patterns: list[tuple[re.Pattern[str], object]] = [
        (re.compile(r"`([^`]+)`"), lambda m: f"<code>{html.escape(m.group(1))}</code>"),
        (
            re.compile(r"\*\*([^*]+)\*\*"),
            lambda m: f"<strong>{html.escape(m.group(1))}</strong>",
        ),
        (
            re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"),
            lambda m: f"<em>{html.escape(m.group(1))}</em>",
        ),
        (
            re.compile(r"\[([^\]]+)\]\(([^)]+)\)"),
            lambda m: (
                f'<a href="{html.escape(m.group(2), quote=True)}">'
                f"{html.escape(m.group(1))}</a>"
            ),
        ),
    ]
    while i < len(text):
        nearest = None
        nearest_pos = len(text)
        nearest_fn = None
        for pattern, fn in patterns:
            match = pattern.search(text, i)
            if match and match.start() < nearest_pos:
                nearest = match
                nearest_pos = match.start()
                nearest_fn = fn
        if nearest is None or nearest_fn is None:
            parts.append(html.escape(text[i:]))
            break
        if nearest_pos > i:
            parts.append(html.escape(text[i:nearest_pos]))
        parts.append(nearest_fn(nearest))  # type: ignore[operator]
        i = nearest.end()
    return "".join(parts)


def _split_table_cells(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.strip() for cell in raw.split("|")]


def _render_table(rows: list[str]) -> str:
    body_rows = [row for row in rows if not _TABLE_SEP.match(row)]
    if not body_rows:
        return ""
    header = _split_table_cells(body_rows[0])
    data = [_split_table_cells(row) for row in body_rows[1:]]
    parts = ['<div class="table-wrap"><table class="faq-table"><thead><tr>']
    parts.extend(f"<th>{_inline_format(cell)}</th>" for cell in header)
    parts.append("</tr></thead><tbody>")
    for row in data:
        parts.append("<tr>")
        cells = row + [""] * max(0, len(header) - len(row))
        for cell in cells[: len(header)]:
            parts.append(f"<td>{_inline_format(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_markdown(source: str) -> str:
    lines = source.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_ul = False
    in_ol = False
    in_p: list[str] = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def flush_p() -> None:
        nonlocal in_p
        if in_p:
            out.append("<p>" + _inline_format(" ".join(in_p)) + "</p>")
            in_p = []

    while i < len(lines):
        line = lines[i]
        if _CODE_FENCE.match(line.strip()):
            flush_p()
            close_lists()
            i += 1
            code: list[str] = []
            while i < len(lines) and not _CODE_FENCE.match(lines[i].strip()):
                code.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue

        if not line.strip():
            flush_p()
            close_lists()
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_p()
            close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline_format(heading.group(2))}</h{level}>")
            i += 1
            continue

        if _TABLE_ROW.match(line.strip()):
            flush_p()
            close_lists()
            table_rows: list[str] = []
            while i < len(lines) and _TABLE_ROW.match(lines[i].strip()):
                table_rows.append(lines[i].strip())
                i += 1
            rendered = _render_table(table_rows)
            if rendered:
                out.append(rendered)
            continue

        ul = _UL_ITEM.match(line)
        if ul:
            flush_p()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_format(ul.group(1))}</li>")
            i += 1
            continue

        ol = _OL_ITEM.match(line)
        if ol:
            flush_p()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_format(ol.group(2))}</li>")
            i += 1
            continue

        close_lists()
        in_p.append(line.strip())
        i += 1

    flush_p()
    close_lists()
    return "\n".join(out)
