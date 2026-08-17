from __future__ import annotations

import html

from lab21_bot.data import phrase, rank_label, rank_level, role_label, skill_title
from lab21_bot.models import CommunityRank, JoinKind, RemovalReason, StaffRole, User
from lab21_bot.services.attribution import append_author_footer_html


def _with_reviewer_footer(text: str, reviewer: User | None) -> str:
    body = html.escape((text or "").strip())
    if reviewer is None:
        return body
    return append_author_footer_html(body, reviewer)


def message_application_approved(*, kind: JoinKind, staff_role: StaffRole | str | None = None) -> str:
    if kind is JoinKind.STAFF and staff_role is not None:
        return phrase("application", "approved_staff", role=role_label(str(staff_role)))
    return phrase("application", "approved_community")


def message_skill_validation_approved(skill_ids: list[str]) -> str:
    labels = ", ".join(skill_title(sid) for sid in skill_ids) or "навык"
    return phrase("application", "skill_added", skill=labels)


def message_application_rejected(
    *,
    note: str | None = None,
    reviewer: User | None = None,
) -> str:
    text = (note or "").strip()
    if text:
        body = phrase("application", "rejected_with_note", note=text)
    else:
        body = phrase("application", "rejected")
    return _with_reviewer_footer(body, reviewer)


def message_skill_validation_rejected(
    *,
    note: str | None = None,
    reviewer: User | None = None,
) -> str:
    text = (note or "").strip() or "отклонено"
    body = phrase("application", "skill_rejected", note=text)
    return _with_reviewer_footer(body, reviewer)


def message_member_removed(reason: RemovalReason) -> str:
    if reason is RemovalReason.RULES:
        return phrase("lifecycle", "removed_rules")
    return phrase("lifecycle", "removed_other")


def message_rank_changed(
    rank: CommunityRank | str,
    *,
    previous: CommunityRank | str | None = None,
) -> str:
    current_level = rank_level(str(rank))
    previous_level = rank_level(str(previous)) if previous is not None else None
    if previous_level is not None and current_level > previous_level and str(rank) == "adept":
        return phrase("lifecycle", "rank_promoted_adept")
    if previous_level is not None and current_level < previous_level and str(rank) == "novice":
        return phrase("lifecycle", "rank_demoted_novice")
    if previous_level is None and str(rank) == "adept":
        return phrase("lifecycle", "rank_promoted_adept")
    return phrase("lifecycle", "rank_updated", rank=rank_label(str(rank)))


def message_staff_role_set(role: StaffRole | str) -> str:
    return phrase("lifecycle", "staff_role_set", role=role_label(str(role)))


def message_staff_role_cleared() -> str:
    return phrase("lifecycle", "staff_role_cleared")


def message_order_fulfilled(*, order_id: int, new_rank: CommunityRank | None = None) -> str:
    parts = [phrase("economy", "order_fulfilled", order_id=order_id)]
    if new_rank is not None:
        parts.append(message_rank_changed(new_rank))
    return "\n".join(parts)


def message_order_cancelled(*, order_id: int) -> str:
    return phrase("economy", "order_cancelled", order_id=order_id)


def message_balance_changed(*, amount: int, grant: bool) -> str:
    if grant:
        return phrase("economy", "balance_grant", amount=amount)
    return phrase("economy", "balance_withdraw", amount=amount)


def message_respect_changed(*, amount: int, grant: bool, respect_after: int) -> str:
    verb = "начислен" if grant else "списан"
    return phrase(
        "economy",
        "respect_changed",
        verb=verb,
        amount=amount,
        respect_after=respect_after,
    )


def message_content_rejected(
    *,
    note: str | None = None,
    reviewer: User | None = None,
) -> str:
    text = (note or "").strip()
    body = text if text else phrase("content", "rejected")
    return _with_reviewer_footer(body, reviewer)
