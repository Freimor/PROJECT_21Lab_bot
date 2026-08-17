from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lab21_bot.data import rank_base_grace, rank_level, skill_by_id, skill_requires_validation, skill_title
from lab21_bot.models import (
    AdminAction,
    CommunityRank,
    JoinApplication,
    JoinKind,
    JoinStatus,
    LedgerEntry,
    LedgerType,
    RemovalReason,
    StaffRole,
    User,
)
from lab21_bot.services.access import Permission, require_permission


class ApplicationError(RuntimeError):
    pass


_OPEN_JOIN_STATUSES = (JoinStatus.PENDING, JoinStatus.SKILL_VALIDATION)


def normalize_skill_ids(raw: list[str] | None, *, required: bool = True) -> list[str]:
    if not raw:
        if required:
            raise ApplicationError("Выбери хотя бы один навык")
        return []
    seen: list[str] = []
    for item in raw:
        skill_id = str(item).strip()
        if not skill_id:
            continue
        if skill_by_id(skill_id) is None:
            raise ApplicationError(f"Неизвестный навык: {skill_id}")
        if skill_id not in seen:
            seen.append(skill_id)
    if not seen and required:
        raise ApplicationError("Выбери хотя бы один навык")
    return seen


def application_needs_skill_validation(skill_ids: list[str]) -> bool:
    return any(skill_requires_validation(skill_id) for skill_id in skill_ids)


def default_skill_reject_note(skill_ids: list[str]) -> str:
    for skill_id in skill_ids:
        if skill_requires_validation(skill_id):
            return f"Не прошел валидацию навыка {skill_title(skill_id)}"
    if skill_ids:
        return f"Не прошел валидацию навыка {skill_title(skill_ids[0])}"
    return "Не прошел валидацию навыка"


def compute_expires_at(now: datetime, expire_days: int) -> datetime:
    """Expire at 23:59:59 UTC on the calendar day `expire_days` from `now`."""
    now_utc = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    end_day = now_utc.date() + timedelta(days=expire_days)
    return datetime(end_day.year, end_day.month, end_day.day, 23, 59, 59, tzinfo=UTC)


async def get_pending_application(
    session: AsyncSession,
    user_id: int,
) -> JoinApplication | None:
    return cast(
        JoinApplication | None,
        await session.scalar(
            select(JoinApplication).where(
                JoinApplication.user_id == user_id,
                JoinApplication.status.in_(_OPEN_JOIN_STATUSES),
            )
        ),
    )


async def list_open_skill_validations(
    session: AsyncSession,
    user_id: int,
) -> list[JoinApplication]:
    rows = await session.scalars(
        select(JoinApplication)
        .where(
            JoinApplication.user_id == user_id,
            JoinApplication.status == JoinStatus.SKILL_VALIDATION,
        )
        .order_by(JoinApplication.created_at.asc())
    )
    return list(rows)


async def get_open_skill_validation(
    session: AsyncSession,
    user_id: int,
) -> JoinApplication | None:
    apps = await list_open_skill_validations(session, user_id)
    return apps[0] if apps else None


async def pending_validation_skill_ids(
    session: AsyncSession,
    user_id: int,
) -> list[str]:
    seen: list[str] = []
    for app in await list_open_skill_validations(session, user_id):
        for sid in app.skill_ids or []:
            if sid not in seen:
                seen.append(sid)
    return seen


async def create_skill_validation_request(
    session: AsyncSession,
    user: User,
    skill_ids: list[str],
    *,
    expire_days: int = 7,
    note: str | None = None,
    actor_id: int | None = None,
    now: datetime | None = None,
) -> list[JoinApplication]:
    """Queue one skill-validation application per skill (no merging)."""
    from lab21_bot.services.skill_catalog import reload_skills_cache

    await reload_skills_cache(session)
    if not user.is_approved or user.staff_role is not None:
        raise ApplicationError("Запрос навыка доступен только участникам сообщества")
    now = now or datetime.now(UTC)
    skills = normalize_skill_ids(skill_ids)
    need_validation = [sid for sid in skills if skill_requires_validation(sid)]
    if not need_validation:
        raise ApplicationError("Эти навыки не требуют валидации")
    have = set(user.skill_ids or [])
    need_validation = [sid for sid in need_validation if sid not in have]
    if not need_validation:
        raise ApplicationError("Навык уже есть у участника")

    already_pending = set(await pending_validation_skill_ids(session, user.telegram_id))
    to_create = [sid for sid in need_validation if sid not in already_pending]
    if not to_create:
        return await list_open_skill_validations(session, user.telegram_id)

    note_text = (note or "").strip() or "Запрос на добавление навыка"
    created: list[JoinApplication] = []
    for sid in to_create:
        application = JoinApplication(
            user_id=user.telegram_id,
            kind=JoinKind.COMMUNITY,
            status=JoinStatus.SKILL_VALIDATION,
            bio=None,
            skills_text=note_text,
            skill_ids=[sid],
            created_at=now,
            expires_at=compute_expires_at(now, expire_days),
        )
        session.add(application)
        created.append(application)
        if actor_id is not None:
            session.add(
                AdminAction(
                    actor_id=actor_id,
                    action="skill_validation_create",
                    target_id=user.telegram_id,
                    details={"skills": [sid]},
                )
            )
    await session.flush()
    return created


@dataclass(frozen=True, slots=True)
class MemberSkillsUpdate:
    added: list[str]
    removed: list[str]
    pending_validation: list[str]


async def _apply_join_base_grace(
    session: AsyncSession,
    user: User,
    actor: User,
    application_id: int,
) -> None:
    from lab21_bot.services.ranks_catalog import catalog_key

    rank_key = catalog_key(user.rank) or "novice"
    # Heal legacy rows that stored Enum.name (NOVICE) instead of value (novice).
    if str(user.rank) != rank_key:
        try:
            user.rank = CommunityRank(rank_key)
        except ValueError:
            user.rank = rank_key
    base = rank_base_grace(rank_key)
    if base <= 0:
        return
    user.balance += base
    session.add(
        LedgerEntry(
            transaction_group=f"join-base:{application_id}",
            idempotency_key=f"join-base-grace:{application_id}",
            initiator_id=actor.telegram_id,
            account_user_id=user.telegram_id,
            delta=base,
            balance_after=user.balance,
            entry_type=LedgerType.GRANT,
            reason=f"Базовая 🙏 при вступлении ({rank_key})",
        )
    )


async def set_member_rank(
    session: AsyncSession,
    actor: User,
    target: User,
    rank_id: str,
) -> None:
    require_permission(actor, Permission.MANAGE_STAFF)
    if target.staff_role is not None:
        raise ApplicationError("Ранг задаётся только участникам сообщества")
    from lab21_bot.services.ranks_catalog import rank_by_id

    key = rank_id.strip()
    if rank_by_id(key) is None:
        raise ApplicationError(f"Неизвестный ранг: {key}")
    previous = str(target.rank)
    if previous == key:
        return
    try:
        target.rank = CommunityRank(key)
    except ValueError:
        target.rank = key
    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_member_rank",
            target_id=target.telegram_id,
            details={"from": previous, "to": key},
        )
    )
    await session.flush()


async def update_member_skills(
    session: AsyncSession,
    actor: User,
    target: User,
    desired_skill_ids: list[str] | None,
    *,
    expire_days: int = 7,
) -> MemberSkillsUpdate:
    from lab21_bot.services.skill_catalog import reload_skills_cache

    await reload_skills_cache(session)
    require_permission(actor, Permission.MANAGE_STAFF)
    if not target.is_approved or target.staff_role is not None:
        raise ApplicationError("Навыки задаются только участникам сообщества")
    desired = normalize_skill_ids(desired_skill_ids, required=False)
    current = list(target.skill_ids or [])
    current_set = set(current)
    desired_set = set(desired)

    removed = [sid for sid in current if sid not in desired_set]
    to_add = [sid for sid in desired if sid not in current_set]
    instant = [sid for sid in to_add if not skill_requires_validation(sid)]
    pending = [sid for sid in to_add if skill_requires_validation(sid)]

    new_skills = [sid for sid in current if sid not in set(removed)]
    for sid in instant:
        if sid not in new_skills:
            new_skills.append(sid)
    target.skill_ids = new_skills

    if pending:
        await create_skill_validation_request(
            session,
            target,
            pending,
            expire_days=expire_days,
            note="Назначено сотрудником — требуется валидация",
            actor_id=actor.telegram_id,
        )

    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="set_member_skills",
            target_id=target.telegram_id,
            details={
                "skills": new_skills,
                "added": instant,
                "removed": removed,
                "pending_validation": pending,
            },
        )
    )
    await session.flush()
    return MemberSkillsUpdate(added=instant, removed=removed, pending_validation=pending)


async def request_member_skill(
    session: AsyncSession,
    user: User,
    skill_id: str,
    *,
    expire_days: int = 7,
) -> tuple[str, JoinApplication | None]:
    """Member self-service skill add. Returns ``(mode, application?)``.

    mode: ``added`` | ``validation`` | ``owned``
    """
    from lab21_bot.services.skill_catalog import reload_skills_cache

    await reload_skills_cache(session)
    if not user.is_approved or user.staff_role is not None:
        raise ApplicationError("Доступно только участникам сообщества")
    skills = normalize_skill_ids([skill_id])
    sid = skills[0]
    if sid in set(user.skill_ids or []):
        return "owned", None
    if skill_requires_validation(sid):
        apps = await create_skill_validation_request(
            session,
            user,
            [sid],
            expire_days=expire_days,
            note="Запрос участника на добавление навыка",
        )
        return "validation", apps[0] if apps else None
    user.skill_ids = [*(user.skill_ids or []), sid]
    session.add(
        AdminAction(
            actor_id=user.telegram_id,
            action="member_skill_self_add",
            target_id=user.telegram_id,
            details={"skill_id": sid},
        )
    )
    await session.flush()
    return "added", None


async def remove_member_skill(
    session: AsyncSession,
    user: User,
    skill_id: str,
) -> bool:
    """Member self-service skill remove. Returns True if removed."""
    from lab21_bot.services.skill_catalog import reload_skills_cache

    await reload_skills_cache(session)
    if not user.is_approved or user.staff_role is not None:
        raise ApplicationError("Доступно только участникам сообщества")
    skills = normalize_skill_ids([skill_id], required=False)
    if not skills:
        return False
    sid = skills[0]
    current = list(user.skill_ids or [])
    if sid not in current:
        return False
    user.skill_ids = [item for item in current if item != sid]
    session.add(
        AdminAction(
            actor_id=user.telegram_id,
            action="member_skill_self_remove",
            target_id=user.telegram_id,
            details={"skill_id": sid},
        )
    )
    await session.flush()
    return True


async def submit_application(
    session: AsyncSession,
    user: User,
    kind: JoinKind,
    *,
    expire_days: int = 7,
    now: datetime | None = None,
    bio: str | None = None,
    skills_text: str | None = None,
    skill_ids: list[str] | None = None,
) -> JoinApplication:
    """Create a join application.

    Community applicants describe skills in free text (`skills_text`).
    Catalog `skill_ids` are assigned later by staff on approval.
    """
    now = now or datetime.now(UTC)
    if user.is_approved and kind is JoinKind.COMMUNITY:
        raise ApplicationError("Вы уже приняты в сообщество")
    if user.staff_role is not None and kind is JoinKind.STAFF:
        raise ApplicationError("Вы уже сотрудник")
    existing = await get_pending_application(session, user.telegram_id)
    if existing is not None:
        raise ApplicationError("Заявка уже ожидает решения")

    normalized_skills: list[str] = []
    status = JoinStatus.PENDING
    bio_text: str | None = None
    skills_free_text: str | None = None
    if kind is JoinKind.COMMUNITY:
        bio_text = (bio or "").strip()
        if not bio_text:
            raise ApplicationError("Кратко расскажи о себе")
        skills_free_text = (skills_text or "").strip()
        if not skills_free_text:
            raise ApplicationError("Укажи свои навыки текстом")
        # Optional legacy path: pre-mapped catalog ids (tests / old callers).
        if skill_ids:
            normalized_skills = normalize_skill_ids(skill_ids)
            if application_needs_skill_validation(normalized_skills):
                status = JoinStatus.SKILL_VALIDATION

    application = JoinApplication(
        user_id=user.telegram_id,
        kind=kind,
        status=status,
        bio=bio_text,
        skills_text=skills_free_text,
        skill_ids=normalized_skills,
        created_at=now,
        expires_at=compute_expires_at(now, expire_days),
    )
    session.add(application)
    await session.flush()
    return application


async def list_pending_applications(
    session: AsyncSession,
    kind: JoinKind | None = None,
    *,
    status: JoinStatus | None = None,
) -> list[JoinApplication]:
    statuses = (status,) if status is not None else _OPEN_JOIN_STATUSES
    query = (
        select(JoinApplication)
        .where(JoinApplication.status.in_(statuses))
        .options(selectinload(JoinApplication.user))
        .order_by(JoinApplication.created_at.asc())
    )
    if kind is not None:
        query = query.where(JoinApplication.kind == kind)
    rows = await session.scalars(query)
    return list(rows)


async def list_community_members(session: AsyncSession) -> list[User]:
    rows = await session.scalars(
        select(User)
        .where(
            User.is_approved.is_(True),
            User.staff_role.is_(None),
            User.is_active.is_(True),
        )
        .order_by(User.full_name)
    )
    return list(rows)


@dataclass(frozen=True, slots=True)
class MemberListRow:
    user: User
    grace_delta: int
    respect_delta: int


async def list_community_members_filtered(
    session: AsyncSession,
    *,
    rank: CommunityRank | None = None,
    since: datetime | None = None,
    sort: str = "name",
    sort_asc: bool = True,
) -> list[MemberListRow]:
    members = await list_community_members(session)
    if rank is not None:
        members = [user for user in members if user.rank is rank]

    grace_delta: dict[int, int] = {user.telegram_id: 0 for user in members}
    respect_delta: dict[int, int] = {user.telegram_id: 0 for user in members}
    if since is not None and members:
        ids = [user.telegram_id for user in members]
        grace_types = {
            LedgerType.GRANT,
            LedgerType.WITHDRAW,
            LedgerType.TRANSFER_OUT,
            LedgerType.TRANSFER_IN,
            LedgerType.PURCHASE_RESERVE,
            LedgerType.PURCHASE_REFUND,
            LedgerType.ADJUSTMENT,
            LedgerType.POST_REWARD,
            LedgerType.MEME_REWARD,
        }
        respect_types = {LedgerType.RESPECT_GRANT, LedgerType.RESPECT_WITHDRAW}
        rows = await session.execute(
            select(
                LedgerEntry.account_user_id,
                LedgerEntry.entry_type,
                func.coalesce(func.sum(LedgerEntry.delta), 0),
            )
            .where(
                LedgerEntry.account_user_id.in_(ids),
                LedgerEntry.created_at >= since,
                LedgerEntry.entry_type.in_(grace_types | respect_types),
            )
            .group_by(LedgerEntry.account_user_id, LedgerEntry.entry_type)
        )
        for user_id, entry_type, total in rows.all():
            amount = int(total or 0)
            if entry_type in grace_types:
                grace_delta[int(user_id)] = grace_delta.get(int(user_id), 0) + amount
            else:
                respect_delta[int(user_id)] = respect_delta.get(int(user_id), 0) + amount
    else:
        for user in members:
            grace_delta[user.telegram_id] = user.balance
            respect_delta[user.telegram_id] = user.respect

    result = [
        MemberListRow(
            user=user,
            grace_delta=grace_delta.get(user.telegram_id, 0),
            respect_delta=respect_delta.get(user.telegram_id, 0),
        )
        for user in members
    ]

    reverse = not sort_asc
    if sort == "grace":
        result.sort(key=lambda row: (row.grace_delta, row.user.full_name), reverse=reverse)
    elif sort == "respect":
        result.sort(key=lambda row: (row.respect_delta, row.user.full_name), reverse=reverse)
    elif sort == "rank":
        result.sort(
            key=lambda row: (rank_level(str(row.user.rank)), row.user.full_name),
            reverse=reverse,
        )
    else:
        result.sort(key=lambda row: row.user.full_name.lower(), reverse=reverse)
    return result


def clear_removal(user: User) -> None:
    user.removal_reason = None
    user.removed_at = None
    user.removed_by = None
    user.is_active = True


async def resolve_application(
    session: AsyncSession,
    actor: User,
    application_id: int,
    *,
    approve: bool,
    staff_role: StaffRole | str | None = None,
    note: str | None = None,
    skill_ids: list[str] | None = None,
    now: datetime | None = None,
) -> JoinApplication:
    require_permission(actor, Permission.MANAGE_STAFF)
    now = now or datetime.now(UTC)
    application = await session.scalar(
        select(JoinApplication)
        .where(JoinApplication.id == application_id)
        .options(selectinload(JoinApplication.user))
        .with_for_update()
    )
    if application is None or application.status not in _OPEN_JOIN_STATUSES:
        raise ApplicationError("Заявка уже обработана или не существует")

    user = application.user
    application.decided_by = actor.telegram_id
    application.decided_at = now
    was_skill_validation = application.status is JoinStatus.SKILL_VALIDATION
    already_member = bool(user.is_approved)

    if (
        approve
        and application.kind is JoinKind.COMMUNITY
        and skill_ids is not None
        and not was_skill_validation
    ):
        application.skill_ids = normalize_skill_ids(skill_ids, required=False)

    resolved_skills = list(application.skill_ids or [])

    pending_after_join: list[str] = []

    if approve:
        from lab21_bot.services.skill_catalog import reload_skills_cache

        await reload_skills_cache(session)
        application.decision_note = note
        if application.kind is JoinKind.STAFF:
            if staff_role is None:
                raise ApplicationError("Для сотрудника нужно выбрать роль")
            from lab21_bot.services.ranks_catalog import role_by_id

            role_meta = role_by_id(str(staff_role))
            if role_meta and role_meta.get("is_unique"):
                existing_unique = await session.scalar(
                    select(User).where(
                        User.staff_role == str(staff_role),
                        User.telegram_id != user.telegram_id,
                    )
                )
                if existing_unique is not None:
                    raise ApplicationError("Уникальная роль уже назначена другому пользователю")
            user.staff_role = staff_role
            user.balance = 0
            user.respect = 0
        elif was_skill_validation:
            # Staff confirmed validation — grant the listed skills.
            if already_member:
                merged = list(dict.fromkeys([*(user.skill_ids or []), *resolved_skills]))
                user.skill_ids = merged
            else:
                user.skill_ids = resolved_skills
                await _apply_join_base_grace(session, user, actor, application.id)
        else:
            # New community join (PENDING): grant free skills; queue the rest.
            instant = [
                sid for sid in resolved_skills if not skill_requires_validation(sid)
            ]
            pending_after_join = [
                sid for sid in resolved_skills if skill_requires_validation(sid)
            ]
            user.skill_ids = instant
            await _apply_join_base_grace(session, user, actor, application.id)
        if (
            not was_skill_validation
            and application.bio
            and not (user.bio or "").strip()
        ):
            user.bio = application.bio.strip()
        user.is_approved = True
        clear_removal(user)
        application.status = JoinStatus.APPROVED
        action = (
            "approve_skill_validation" if was_skill_validation else "approve_join"
        )
        if pending_after_join:
            await create_skill_validation_request(
                session,
                user,
                pending_after_join,
                note="Назначено при принятии в сообщество — требуется валидация",
                actor_id=actor.telegram_id,
                now=now,
            )
    else:
        if was_skill_validation and not (note or "").strip():
            application.decision_note = default_skill_reject_note(resolved_skills)
        else:
            application.decision_note = note
        application.status = JoinStatus.REJECTED
        action = (
            "reject_skill_validation" if was_skill_validation else "reject_join"
        )

    details: dict[str, object] = {
        "application_id": application.id,
        "kind": application.kind.value,
        "staff_role": str(staff_role) if staff_role else None,
    }
    if application.skills_text:
        details["skills_text"] = application.skills_text
    if was_skill_validation or resolved_skills:
        details["skills"] = resolved_skills
    if application.decision_note:
        details["note"] = application.decision_note

    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action=action,
            target_id=user.telegram_id,
            details=details,
        )
    )
    await session.flush()
    return application


async def remove_member(
    session: AsyncSession,
    actor: User,
    target: User,
    reason: RemovalReason,
    *,
    now: datetime | None = None,
) -> User:
    require_permission(actor, Permission.MANAGE_STAFF)
    now = now or datetime.now(UTC)
    if target.telegram_id == actor.telegram_id:
        raise ApplicationError("Нельзя удалить себя")
    if not target.is_approved and target.staff_role is None:
        raise ApplicationError("Пользователь уже не состоит в системе")

    previous_role = str(target.staff_role) if target.staff_role else None
    was_approved = target.is_approved
    target.staff_role = None
    target.is_approved = False
    target.is_active = False
    target.removal_reason = reason
    target.removed_at = now
    target.removed_by = actor.telegram_id

    pending = await get_pending_application(session, target.telegram_id)
    if pending is not None:
        pending.status = JoinStatus.REJECTED
        pending.decided_by = actor.telegram_id
        pending.decided_at = now
        pending.decision_note = "Отклонено при удалении пользователя"

    session.add(
        AdminAction(
            actor_id=actor.telegram_id,
            action="remove_member",
            target_id=target.telegram_id,
            details={
                "reason": reason.value,
                "previous_staff_role": previous_role,
                "was_approved": was_approved,
            },
        )
    )
    await session.flush()
    return target


async def expire_pending_applications(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[JoinApplication]:
    now = now or datetime.now(UTC)
    pending = await session.scalars(
        select(JoinApplication)
        .where(
            JoinApplication.status.in_(_OPEN_JOIN_STATUSES),
            JoinApplication.expires_at <= now,
        )
        .options(selectinload(JoinApplication.user))
        .with_for_update()
    )
    expired: list[JoinApplication] = []
    for application in pending:
        application.status = JoinStatus.EXPIRED
        application.decided_at = now
        application.decision_note = "Автоматический отказ: срок заявки истёк"
        expired.append(application)
    await session.flush()
    return expired
