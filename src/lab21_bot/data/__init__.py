"""Editable content catalog loaded from JSON files in ``lab21_bot/data``."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent


@cache
def load_json(name: str) -> dict[str, Any]:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"{name} must contain a JSON object")
    return data


def ranks_data() -> dict[str, Any]:
    return load_json("ranks.json")


def system_settings_data() -> dict[str, Any]:
    return load_json("system_settings.json")


def phrases_data() -> dict[str, Any]:
    return load_json("phrases.json")


def interview_data() -> dict[str, Any]:
    return load_json("interview.json")


def llm_prompts_data() -> dict[str, Any]:
    return load_json("llm_prompts.json")


def prefixes_data() -> dict[str, Any]:
    return load_json("prefixes.json")


def respect_prefix(respect: int) -> str:
    """Highest prefix whose min_respect <= respect."""
    value = max(0, int(respect))
    items = prefixes_data().get("prefixes") or []
    label = "обычный"
    best = -1
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            minimum = int(item.get("min_respect", 0))
        except (TypeError, ValueError):
            continue
        if minimum <= value and minimum >= best:
            best = minimum
            label = str(item.get("label") or label)
    return label


def respect_prefix_legend() -> list[dict[str, str]]:
    items = prefixes_data().get("prefixes") or []
    result: list[dict[str, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        minimum = int(item.get("min_respect", 0))
        label = str(item.get("label") or "")
        if index + 1 < len(items) and isinstance(items[index + 1], dict):
            nxt = int(items[index + 1].get("min_respect", minimum)) - 1
            span = f"{minimum}–{nxt}"
        else:
            span = f"{minimum}+"
        result.append({"label": label, "span": span, "min_respect": str(minimum)})
    return result


def phrase(*path: str, **fields: object) -> str:
    node: Any = phrases_data()
    for key in path:
        node = node[key]
    text = str(node)
    return text.format(**fields) if fields else text


def list_season_phrase_keys() -> list[dict[str, str | int]]:
    """Keys from phrases.json → presence.seasons, for the season admin select."""
    presence = phrases_data().get("presence") or {}
    seasons = presence.get("seasons") if isinstance(presence, dict) else None
    if not isinstance(seasons, dict):
        return []
    items: list[dict[str, str | int]] = []
    for key, value in seasons.items():
        name = str(key).strip()
        if not name:
            continue
        count = len(value) if isinstance(value, list) else 0
        items.append({"key": name, "phrase_count": count})
    items.sort(key=lambda item: str(item["key"]))
    return items


def phrase_choices(*path: str) -> list[str]:
    node: Any = phrases_data()
    try:
        for key in path:
            node = node[key]
    except (KeyError, TypeError):
        return []
    if isinstance(node, list):
        return [str(item) for item in node if str(item).strip()]
    if isinstance(node, str) and node.strip():
        return [node]
    return []


def random_phrase(*path: str, **fields: object) -> str:
    import random

    choices = phrase_choices(*path)
    if not choices:
        return ""
    text = random.choice(choices)
    return text.format(**fields) if fields else text


def rank_label(key: str) -> str:
    from lab21_bot.services.ranks_catalog import rank_by_id

    item = rank_by_id(key)
    if item is not None:
        return str(item.get("label") or key)
    ranks = ranks_data().get("ranks", {})
    entry = ranks.get(key) if isinstance(ranks, dict) else None
    if isinstance(entry, dict):
        return str(entry.get("label") or key)
    return key


def role_label(key: str) -> str:
    from lab21_bot.services.ranks_catalog import role_by_id

    item = role_by_id(key)
    if item is not None:
        return str(item.get("label") or key)
    roles = ranks_data().get("roles", {})
    entry = roles.get(key) if isinstance(roles, dict) else None
    if isinstance(entry, dict):
        return str(entry.get("label") or key)
    return key


def rank_labels() -> dict[str, str]:
    from lab21_bot.services.ranks_catalog import get_ranks_snapshot

    return {str(item["id"]): str(item.get("label") or item["id"]) for item in get_ranks_snapshot()}


def role_labels() -> dict[str, str]:
    from lab21_bot.services.ranks_catalog import get_roles_snapshot

    return {str(item["id"]): str(item.get("label") or item["id"]) for item in get_roles_snapshot()}


def rank_colors() -> dict[str, str]:
    from lab21_bot.services.ranks_catalog import get_ranks_snapshot

    return {
        str(item["id"]): str(item.get("color") or "#a89878") for item in get_ranks_snapshot()
    }


def role_colors() -> dict[str, str]:
    from lab21_bot.services.ranks_catalog import get_roles_snapshot

    return {
        str(item["id"]): str(item.get("color") or "#6b7c93") for item in get_roles_snapshot()
    }


def role_legend() -> list[dict[str, str]]:
    from lab21_bot.services.ranks_catalog import get_roles_snapshot

    return [
        {
            "key": str(item["id"]),
            "label": str(item.get("label") or item["id"]),
            "badge": str(item.get("badge") or "сотрудник"),
            "color": str(item.get("color") or "#6b7c93"),
            "desc": str(item.get("description") or ""),
        }
        for item in get_roles_snapshot()
    ]


def rank_legend() -> list[dict[str, str]]:
    from lab21_bot.services.ranks_catalog import get_ranks_snapshot

    return [
        {
            "key": str(item["id"]),
            "label": str(item.get("label") or item["id"]),
            "level": str(item.get("level") or 0),
            "color": str(item.get("color") or "#a89878"),
            "base_grace": str(item.get("base_grace") or 0),
            "cap_grace": str(item.get("cap_grace") or 0),
        }
        for item in get_ranks_snapshot()
    ]


# Steel tempering color stops: pale yellow → straw → brown → purple → blue
_TEMPER_STOPS: tuple[tuple[int, int, int], ...] = (
    (245, 230, 163),
    (232, 184, 74),
    (196, 120, 58),
    (139, 74, 139),
    (58, 107, 196),
)


def _lerp_channel(start: int, end: int, t: float) -> int:
    return int(round(start + (end - start) * t))


def temper_color(value: int, maximum: int) -> str:
    """Map a value onto the metal tempering spectrum (0 = pale yellow, max = blue)."""
    if maximum <= 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, float(value) / float(maximum)))
    stops = _TEMPER_STOPS
    scaled = t * (len(stops) - 1)
    index = min(int(scaled), len(stops) - 2)
    local = scaled - index
    start = stops[index]
    end = stops[index + 1]
    rgb = tuple(_lerp_channel(start[i], end[i], local) for i in range(3))
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def contrast_ink(hex_color: str) -> str:
    raw = hex_color.removeprefix("#")
    if len(raw) != 6:
        return "#1a120c"
    red = int(raw[0:2], 16)
    green = int(raw[2:4], 16)
    blue = int(raw[4:6], 16)
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#1a120c" if luminance > 0.55 else "#ebecec"


def removal_reason_labels() -> dict[str, str]:
    return {key: str(label) for key, label in ranks_data()["removal_reasons"].items()}


def setting_default(key: str) -> int:
    return int(system_settings_data()["defaults"][key])


def setting_ranges() -> dict[str, tuple[int, int]]:
    return {
        key: (int(bounds[0]), int(bounds[1]))
        for key, bounds in system_settings_data()["ranges"].items()
    }


def interview_questions() -> tuple[str, ...]:
    return tuple(str(item) for item in interview_data()["questions"])


def skills_data() -> dict[str, Any]:
    return load_json("skills.json")


def list_skills() -> list[dict[str, Any]]:
    from lab21_bot.services.skill_catalog import get_skills_snapshot

    return get_skills_snapshot()


def skill_by_id(skill_id: str) -> dict[str, Any] | None:
    needle = skill_id.strip()
    if not needle:
        return None
    for item in list_skills():
        if str(item["id"]) == needle:
            return item
    return None


def skill_title(skill_id: str) -> str:
    item = skill_by_id(skill_id)
    if item is None:
        return skill_id
    return str(item.get("title") or skill_id)


def skill_titles() -> dict[str, str]:
    return {str(item["id"]): str(item.get("title") or item["id"]) for item in list_skills()}


def skill_requires_validation(skill_id: str) -> bool:
    item = skill_by_id(skill_id)
    return bool(item and item.get("requires_validation"))


def skill_validation_description(skill_id: str) -> str:
    item = skill_by_id(skill_id)
    if item is None:
        return ""
    return str(item.get("validation_description") or "").strip()


def skill_validation_descriptions() -> dict[str, str]:
    return {
        str(item["id"]): str(item.get("validation_description") or "").strip()
        for item in list_skills()
        if item.get("requires_validation")
    }


def skill_grace_price(skill_id: str) -> int:
    item = skill_by_id(skill_id)
    if item is None:
        return 0
    return int(item.get("grace_price") or 0)


def skill_respect_reward(skill_id: str) -> int:
    item = skill_by_id(skill_id)
    if item is None:
        return 0
    return int(item.get("respect_reward") or 0)


def skills_grace_sum(skill_ids: list[str]) -> int:
    return sum(skill_grace_price(skill_id) for skill_id in skill_ids)


def skills_respect_sum(skill_ids: list[str]) -> int:
    return sum(skill_respect_reward(skill_id) for skill_id in skill_ids)


def format_skills_price_lines(skill_ids: list[str]) -> str:
    lines: list[str] = []
    for skill_id in skill_ids:
        lines.append(f"• {skill_title(skill_id)} — {skill_grace_price(skill_id)} 🙏")
    return "\n".join(lines) if lines else "—"


def rank_base_grace(rank_key: str) -> int:
    from lab21_bot.services.ranks_catalog import rank_by_id

    item = rank_by_id(rank_key)
    if item is not None:
        return int(item.get("base_grace") or 0)
    ranks = ranks_data().get("ranks", {})
    entry = ranks.get(rank_key) if isinstance(ranks, dict) else None
    if not isinstance(entry, dict):
        return 0
    return int(entry.get("base_grace") or 0)


def rank_cap_grace(rank_key: str) -> int:
    """Upper grace soft-cap for daily decay; 0 disables decay for the rank."""
    from lab21_bot.services.ranks_catalog import rank_by_id

    item = rank_by_id(rank_key)
    if item is not None:
        return int(item.get("cap_grace") or 0)
    ranks = ranks_data().get("ranks", {})
    entry = ranks.get(rank_key) if isinstance(ranks, dict) else None
    if not isinstance(entry, dict):
        return 0
    return int(entry.get("cap_grace") or 0)


def rank_level(rank_key: str) -> int:
    from lab21_bot.services.ranks_catalog import rank_by_id

    item = rank_by_id(rank_key)
    if item is not None:
        return int(item.get("level") or 0)
    ranks = ranks_data().get("ranks", {})
    entry = ranks.get(rank_key) if isinstance(ranks, dict) else None
    if not isinstance(entry, dict):
        return 0
    return int(entry.get("level") or 0)


def rank_can_transfer(rank_key: str) -> bool:
    from lab21_bot.services.ranks_catalog import rank_by_id

    item = rank_by_id(rank_key)
    if item is not None:
        return bool(item.get("can_transfer_grace"))
    return str(rank_key) == "adept"
