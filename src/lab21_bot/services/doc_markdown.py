"""Render project documents. Raw HTML from the source is stripped."""

from __future__ import annotations

import markdown
import nh3

_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
_ATTRS = {
    "a": {"href", "title"},
    "code": {"class"},
    "td": {"align"},
    "th": {"align"},
}

_RENDERER = markdown.Markdown(
    extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    output_format="html",
)


def render_markdown(source: str) -> str:
    _RENDERER.reset()
    rendered = _RENDERER.convert(source or "")
    return nh3.clean(
        rendered,
        tags=_TAGS,
        attributes=_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )
