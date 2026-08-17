from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from lab21_bot.admin.deps import CurrentUser, DbSession, RequireManageEconomy, RequireManageStaff, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.data import list_skills, setting_default
from lab21_bot.models import JoinApplication, JoinKind, JoinStatus, RemovalReason, StaffRole, User
from lab21_bot.services.access import (
    AccessDenied,
    Permission,
    find_user,
    has_permission,
    list_staff,
    set_staff_role,
)
from lab21_bot.services.applications import (
    ApplicationError,
    pending_validation_skill_ids,
    list_community_members_filtered,
    list_pending_applications,
    remove_member,
    resolve_application,
    set_member_rank,
    update_member_skills,
)
from lab21_bot.services.ranks_catalog import get_ranks_snapshot
from lab21_bot.services.commands import sync_user_commands_http
from lab21_bot.services.economy import EconomyError, change_balance, change_respect
from lab21_bot.services.notify import notify_telegram_user
from lab21_bot.services.periods import PERIOD_KEYS, PERIOD_LABELS, parse_period, period_since
from lab21_bot.services.settings import SettingError, get_int_setting
from lab21_bot.services.skill_catalog import (
    SkillCatalogError,
    create_skill,
    delete_skill,
    get_skill,
    list_skill_rows,
    update_skill,
)
from lab21_bot.services.ranks_catalog import (
    PERMISSION_LABELS,
    RanksCatalogError,
    create_rank,
    create_role,
    delete_rank,
    delete_role,
    get_rank,
    get_role,
    get_roles_snapshot,
    list_rank_rows,
    list_role_rows,
    update_rank,
    update_role,
)
from lab21_bot.services.staff_chat import invite_to_staff_chat, kick_from_staff_chat
from lab21_bot.services.user_messages import (
    message_application_approved,
    message_application_rejected,
    message_balance_changed,
    message_member_removed,
    message_respect_changed,
    message_skill_validation_approved,
    message_skill_validation_rejected,
    message_staff_role_cleared,
    message_staff_role_set,
)
from lab21_bot.services.telegram_profile import (
    TelegramProfileError,
    download_telegram_file,
    sync_users_profiles,
)

router = APIRouter(tags=["community"])


def _flash(path: str, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(f"{path}?error={quote(error)}", status_code=303)
    return RedirectResponse(f"{path}?message={quote(message or 'Сохранено')}", status_code=303)


async def _assignable_roles(session: DbSession) -> list[str]:
    roles = get_roles_snapshot()
    result: list[str] = []
    for item in roles:
        role_id = str(item["id"])
        if item.get("is_unique"):
            taken = await session.scalar(
                select(User.telegram_id).where(User.staff_role == role_id).limit(1)
            )
            if taken is not None:
                continue
        result.append(role_id)
    return result


def _permission_choices() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in PERMISSION_LABELS.items()]


def _form_permissions(raw: list[str] | str | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    return [str(item) for item in raw if str(item).strip()]


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "on", "yes"}


@router.get("/people", response_class=HTMLResponse)
@router.get("/community", response_class=HTMLResponse)
async def community_home(user: CurrentUser) -> RedirectResponse:
    if has_permission(user, Permission.MANAGE_STAFF):
        return RedirectResponse("/community/applications", status_code=303)
    return RedirectResponse("/community/members", status_code=303)


@router.get("/staff", response_class=HTMLResponse)
@router.get("/adepts", response_class=HTMLResponse)
async def people_legacy_redirect() -> RedirectResponse:
    return RedirectResponse("/community/staff", status_code=303)


@router.get("/community/applications", response_class=HTMLResponse)
async def community_applications(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: RequireManageStaff,
) -> HTMLResponse:
    applications = await list_pending_applications(session)
    skill_apps = [item for item in applications if item.status is JoinStatus.SKILL_VALIDATION]
    pending_apps = [item for item in applications if item.status is JoinStatus.PENDING]
    await sync_users_profiles(
        session,
        [item.user for item in applications if item.user is not None],
        settings.telegram_bot_token.get_secret_value(),
    )
    return await render(
        request,
        "community_applications.html",
        user=user,
        session=session,
        community_section="applications",
        skill_apps=skill_apps,
        pending_apps=pending_apps,
        roles=await _assignable_roles(session),
        skills=list_skills(),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/community/staff", response_class=HTMLResponse)
async def community_staff(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: RequireManageStaff,
) -> HTMLResponse:
    staff = await list_staff(session)
    await sync_users_profiles(
        session,
        staff,
        settings.telegram_bot_token.get_secret_value(),
    )
    return await render(
        request,
        "community_staff.html",
        user=user,
        session=session,
        community_section="staff",
        staff=staff,
        roles=await _assignable_roles(session),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/community/members", response_class=HTMLResponse)
async def community_members(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> HTMLResponse:
    can_staff = has_permission(user, Permission.MANAGE_STAFF)
    can_economy = has_permission(user, Permission.MANAGE_ECONOMY)
    if not can_staff and not can_economy:
        return RedirectResponse("/", status_code=303)
    period = parse_period(request.query_params.get("period"), default="all")
    sort = request.query_params.get("sort", "rank")
    if sort not in {"grace", "respect", "rank"}:
        sort = "rank"
    sort_dir = request.query_params.get("dir", "asc")
    sort_asc = sort_dir != "desc"
    since = period_since(period, tz=settings.tz)
    member_rows = await list_community_members_filtered(
        session,
        rank=None,
        since=since,
        sort=sort,
        sort_asc=sort_asc,
    )
    await sync_users_profiles(
        session,
        [row.user for row in member_rows],
        settings.telegram_bot_token.get_secret_value(),
    )
    grace_refill_percent = await get_int_setting(
        session,
        "grace_refill_percent",
        setting_default("grace_refill_percent"),
    )
    grace_decay_percent = await get_int_setting(
        session,
        "grace_decay_percent",
        setting_default("grace_decay_percent"),
    )
    return await render(
        request,
        "community_members.html",
        user=user,
        session=session,
        community_section="members",
        member_rows=member_rows,
        can_staff=can_staff,
        can_economy=can_economy,
        grace_refill_percent=grace_refill_percent,
        grace_decay_percent=grace_decay_percent,
        filter_period=period,
        filter_sort=sort,
        filter_dir="asc" if sort_asc else "desc",
        period_keys=PERIOD_KEYS,
        period_labels=PERIOD_LABELS,
        period_limited=since is not None,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/community/members/{telegram_id}", response_class=HTMLResponse)
async def community_member_edit(
    telegram_id: int,
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    member = await session.get(User, telegram_id)
    if (
        member is None
        or not member.is_approved
        or member.staff_role is not None
        or not member.is_active
    ):
        return _flash("/community/members", error="Участник не найден")
    pending_skills = await pending_validation_skill_ids(session, member.telegram_id)
    return await render(
        request,
        "community_member_edit.html",
        user=user,
        session=session,
        community_section="members",
        member=member,
        ranks=get_ranks_snapshot(),
        skills=list_skills(),
        pending_skills=pending_skills,
        can_economy=has_permission(user, Permission.MANAGE_ECONOMY),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/community/members/{telegram_id}/update")
async def community_member_update(
    telegram_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStaff,
    rank: Annotated[str, Form()],
    skill_ids: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    member = await session.get(User, telegram_id)
    if (
        member is None
        or not member.is_approved
        or member.staff_role is not None
        or not member.is_active
    ):
        return _flash("/community/members", error="Участник не найден")
    try:
        previous_rank = str(member.rank)
        await set_member_rank(session, actor, member, rank)
        result = await update_member_skills(
            session,
            actor,
            member,
            list(skill_ids or []),
        )
        token = settings.telegram_bot_token.get_secret_value()
        if previous_rank != str(member.rank):
            from lab21_bot.services.user_messages import message_rank_changed

            await notify_telegram_user(
                token,
                member.telegram_id,
                message_rank_changed(member.rank, previous=previous_rank),
            )
        parts = ["Участник сохранён"]
        if result.pending_validation:
            parts.append(
                f"на валидацию: {len(result.pending_validation)}"
            )
        return _flash(
            f"/community/members/{telegram_id}",
            message="; ".join(parts),
        )
    except ApplicationError as exc:
        return _flash(f"/community/members/{telegram_id}", error=str(exc))


@router.get("/community/skills", response_class=HTMLResponse)
async def community_skills(
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    sort = request.query_params.get("sort", "level")
    if sort not in {"level", "grace", "respect", "count", "title"}:
        sort = "level"
    sort_dir = request.query_params.get("dir", "asc")
    sort_asc = sort_dir != "desc"
    rows = await list_skill_rows(session, sort=sort, sort_asc=sort_asc)
    return await render(
        request,
        "community_skills.html",
        user=user,
        session=session,
        community_section="skills",
        skill_rows=rows,
        filter_sort=sort,
        filter_dir="asc" if sort_asc else "desc",
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/community/skills/{skill_id}", response_class=HTMLResponse)
async def community_skill_edit(
    skill_id: str,
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    skill = await get_skill(session, skill_id)
    if skill is None:
        return _flash("/community/skills", error="Навык не найден")
    return await render(
        request,
        "community_skill_edit.html",
        user=user,
        session=session,
        community_section="skills",
        skill=skill,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/community/skills")
async def community_skills_create(
    session: DbSession,
    actor: RequireManageStaff,
    skill_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    validation_description: Annotated[str, Form()] = "",
    level: Annotated[int, Form()] = 1,
    grace_price: Annotated[int, Form()] = 0,
    respect_reward: Annotated[int, Form()] = 0,
    requires_validation: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await create_skill(
            session,
            actor.telegram_id,
            skill_id=skill_id,
            title=title,
            description=description,
            requires_validation=requires_validation.lower() in {"1", "true", "on", "yes"},
            validation_description=validation_description,
            level=level,
            grace_price=grace_price,
            respect_reward=respect_reward,
        )
        return _flash("/community/skills", message="Навык создан")
    except SkillCatalogError as exc:
        return _flash("/community/skills", error=str(exc))


@router.post("/community/skills/{skill_id}/update")
async def community_skills_update(
    skill_id: str,
    session: DbSession,
    actor: RequireManageStaff,
    title: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    validation_description: Annotated[str, Form()] = "",
    level: Annotated[int, Form()] = 1,
    grace_price: Annotated[int, Form()] = 0,
    respect_reward: Annotated[int, Form()] = 0,
    requires_validation: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await update_skill(
            session,
            actor.telegram_id,
            skill_id,
            title=title,
            description=description,
            requires_validation=requires_validation.lower() in {"1", "true", "on", "yes"},
            validation_description=validation_description,
            level=level,
            grace_price=grace_price,
            respect_reward=respect_reward,
        )
        return _flash(f"/community/skills/{skill_id}", message="Навык сохранён")
    except SkillCatalogError as exc:
        return _flash(f"/community/skills/{skill_id}", error=str(exc))


@router.post("/community/skills/{skill_id}/delete")
async def community_skills_delete(
    skill_id: str,
    session: DbSession,
    actor: RequireManageStaff,
) -> RedirectResponse:
    try:
        await delete_skill(session, actor.telegram_id, skill_id)
        return _flash("/community/skills", message="Навык удалён")
    except SkillCatalogError as exc:
        return _flash("/community/skills", error=str(exc))


@router.get("/community/roles", response_class=HTMLResponse)
async def community_roles(
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    return await render(
        request,
        "community_roles.html",
        user=user,
        session=session,
        community_section="roles",
        role_rows=await list_role_rows(session),
        rank_rows=await list_rank_rows(session),
        permission_choices=_permission_choices(),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/community/roles/{role_id}", response_class=HTMLResponse)
async def community_role_edit(
    role_id: str,
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    role = await get_role(session, role_id)
    if role is None:
        return _flash("/community/roles", error="Роль не найдена")
    return await render(
        request,
        "community_role_edit.html",
        user=user,
        session=session,
        community_section="roles",
        role=role,
        permission_choices=_permission_choices(),
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/community/roles")
async def community_roles_create(
    session: DbSession,
    actor: RequireManageStaff,
    role_id: Annotated[str, Form()],
    label: Annotated[str, Form()],
    badge: Annotated[str, Form()] = "сотрудник",
    color: Annotated[str, Form()] = "#6b7c93",
    description: Annotated[str, Form()] = "",
    is_unique: Annotated[str, Form()] = "",
    permissions: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    try:
        await create_role(
            session,
            actor.telegram_id,
            role_id=role_id,
            label=label,
            badge=badge,
            color=color,
            description=description,
            is_unique=_truthy(is_unique),
            permissions=_form_permissions(permissions),
        )
        return _flash("/community/roles", message="Роль создана")
    except RanksCatalogError as exc:
        return _flash("/community/roles", error=str(exc))


@router.post("/community/roles/{role_id}/update")
async def community_roles_update(
    role_id: str,
    session: DbSession,
    actor: RequireManageStaff,
    label: Annotated[str, Form()],
    badge: Annotated[str, Form()] = "сотрудник",
    color: Annotated[str, Form()] = "#6b7c93",
    description: Annotated[str, Form()] = "",
    sort_order: Annotated[int, Form()] = 0,
    is_unique: Annotated[str, Form()] = "",
    permissions: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    try:
        await update_role(
            session,
            actor.telegram_id,
            role_id,
            label=label,
            badge=badge,
            color=color,
            description=description,
            sort_order=sort_order,
            is_unique=_truthy(is_unique),
            permissions=_form_permissions(permissions),
        )
        return _flash(f"/community/roles/{role_id}", message="Роль сохранена")
    except RanksCatalogError as exc:
        return _flash(f"/community/roles/{role_id}", error=str(exc))


@router.post("/community/roles/{role_id}/delete")
async def community_roles_delete(
    role_id: str,
    session: DbSession,
    actor: RequireManageStaff,
) -> RedirectResponse:
    try:
        await delete_role(session, actor.telegram_id, role_id)
        return _flash("/community/roles", message="Роль удалена")
    except RanksCatalogError as exc:
        return _flash("/community/roles", error=str(exc))


@router.get("/community/ranks/{rank_id}", response_class=HTMLResponse)
async def community_rank_edit(
    rank_id: str,
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    rank = await get_rank(session, rank_id)
    if rank is None:
        return _flash("/community/roles", error="Ранг не найден")
    return await render(
        request,
        "community_rank_edit.html",
        user=user,
        session=session,
        community_section="roles",
        rank=rank,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.post("/community/ranks")
async def community_ranks_create(
    session: DbSession,
    actor: RequireManageStaff,
    rank_id: Annotated[str, Form()],
    label: Annotated[str, Form()],
    level: Annotated[int, Form()] = 0,
    color: Annotated[str, Form()] = "#a89878",
    base_grace: Annotated[int, Form()] = 0,
    cap_grace: Annotated[int, Form()] = 0,
    can_transfer_grace: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await create_rank(
            session,
            actor.telegram_id,
            rank_id=rank_id,
            label=label,
            level=level,
            color=color,
            base_grace=base_grace,
            cap_grace=cap_grace,
            can_transfer_grace=_truthy(can_transfer_grace),
        )
        return _flash("/community/roles", message="Ранг создан")
    except RanksCatalogError as exc:
        return _flash("/community/roles", error=str(exc))


@router.post("/community/ranks/{rank_id}/update")
async def community_ranks_update(
    rank_id: str,
    session: DbSession,
    actor: RequireManageStaff,
    label: Annotated[str, Form()],
    level: Annotated[int, Form()] = 0,
    color: Annotated[str, Form()] = "#a89878",
    sort_order: Annotated[int, Form()] = 0,
    base_grace: Annotated[int, Form()] = 0,
    cap_grace: Annotated[int, Form()] = 0,
    can_transfer_grace: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await update_rank(
            session,
            actor.telegram_id,
            rank_id,
            label=label,
            level=level,
            color=color,
            sort_order=sort_order,
            base_grace=base_grace,
            cap_grace=cap_grace,
            can_transfer_grace=_truthy(can_transfer_grace),
        )
        return _flash(f"/community/ranks/{rank_id}", message="Ранг сохранён")
    except RanksCatalogError as exc:
        return _flash(f"/community/ranks/{rank_id}", error=str(exc))


@router.post("/community/ranks/{rank_id}/delete")
async def community_ranks_delete(
    rank_id: str,
    session: DbSession,
    actor: RequireManageStaff,
) -> RedirectResponse:
    try:
        await delete_rank(session, actor.telegram_id, rank_id)
        return _flash("/community/roles", message="Ранг удалён")
    except RanksCatalogError as exc:
        return _flash("/community/roles", error=str(exc))


@router.post("/community/settings/grace-refill")
@router.post("/people/settings/grace-refill")
async def community_grace_refill_setting(
    session: DbSession,
    actor: CurrentUser,
    grace_refill_percent: Annotated[int, Form()],
    grace_decay_percent: Annotated[int, Form()],
) -> RedirectResponse:
    if not (
        has_permission(actor, Permission.MANAGE_SETTINGS)
        or has_permission(actor, Permission.MANAGE_ECONOMY)
    ):
        return _flash("/community/members", error="Недостаточно прав")
    try:
        from lab21_bot.data import setting_ranges
        from lab21_bot.models import AdminAction, BotSetting

        ranges = setting_ranges()
        for key, value in (
            ("grace_refill_percent", grace_refill_percent),
            ("grace_decay_percent", grace_decay_percent),
        ):
            minimum, maximum = ranges[key]
            if not minimum <= value <= maximum:
                raise SettingError(f"{key}: допустимый диапазон {minimum}–{maximum}")
            setting = await session.get(BotSetting, key)
            if setting is None:
                session.add(
                    BotSetting(
                        key=key,
                        value={"value": value},
                        updated_by=actor.telegram_id,
                    )
                )
            else:
                setting.value = {"value": value}
                setting.updated_by = actor.telegram_id
            session.add(
                AdminAction(
                    actor_id=actor.telegram_id,
                    action="set_setting",
                    details={"key": key, "value": value},
                )
            )
        await session.flush()
        return _flash("/community/members", message="Настройки благодати сохранены")
    except (SettingError, ValueError) as exc:
        return _flash("/community/members", error=str(exc))


def _parse_staff_role(role: str) -> StaffRole | str | None:
    value = role.strip()
    if value in {"", "none"}:
        return None
    from lab21_bot.services.ranks_catalog import role_by_id

    if role_by_id(value) is None:
        raise ValueError(f"Неизвестная роль: {value}")
    try:
        return StaffRole(value)
    except ValueError:
        return value


@router.post("/community/set-role")
@router.post("/people/set-role")
async def set_role(
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStaff,
    target_query: Annotated[str, Form()],
    role: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        target = await find_user(session, target_query)
        if target is None:
            raise AccessDenied("Участник не найден")
        new_role = _parse_staff_role(role)
        previous_role = target.staff_role
        await set_staff_role(session, actor, target, new_role)
        if new_role is not None:
            target.balance = 0
            target.respect = 0
        token = settings.telegram_bot_token.get_secret_value()
        await sync_user_commands_http(token, target)
        text = (
            message_staff_role_set(new_role)
            if new_role is not None
            else message_staff_role_cleared()
        )
        await notify_telegram_user(token, target.telegram_id, text)
        if new_role is not None and previous_role is None:
            await invite_to_staff_chat(token, settings.staff_chat_id, target.telegram_id)
        elif new_role is None and previous_role is not None:
            await kick_from_staff_chat(token, settings.staff_chat_id, target.telegram_id)
        return _flash("/community/staff", message="Роль обновлена")
    except (AccessDenied, ValueError) as exc:
        return _flash("/community/staff", error=str(exc))


@router.post("/community/applications/{application_id}/resolve")
@router.post("/people/applications/{application_id}/resolve")
async def resolve_people_application(
    application_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStaff,
    approve: Annotated[str, Form()],
    staff_role: Annotated[str, Form()] = "watcher",
    note: Annotated[str, Form()] = "",
    skill_ids: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    try:
        approved = approve.lower() in {"1", "true", "yes"}
        existing = await session.get(JoinApplication, application_id)
        if existing is None:
            raise ApplicationError("Заявка не найдена")
        app_user = await session.get(User, existing.user_id)
        role = None
        mapped_skills: list[str] | None = None
        if approved and existing.kind is JoinKind.STAFF:
            role = _parse_staff_role(staff_role)
        if approved and existing.kind is JoinKind.COMMUNITY:
            mapped_skills = list(skill_ids or [])
        was_approved = bool(app_user and app_user.is_approved)
        was_skill_validation = existing.status is JoinStatus.SKILL_VALIDATION
        application = await resolve_application(
            session,
            actor,
            application_id,
            approve=approved,
            staff_role=role,
            note=note.strip() or None,
            skill_ids=mapped_skills,
        )
        token = settings.telegram_bot_token.get_secret_value()
        if approved:
            if was_skill_validation and was_approved:
                text = message_skill_validation_approved(list(application.skill_ids or []))
            else:
                text = message_application_approved(
                    kind=application.kind,
                    staff_role=application.user.staff_role,
                )
            pending_skills = await pending_validation_skill_ids(session, application.user_id)
            if (
                not was_skill_validation
                and pending_skills
            ):
                label = (
                    f"Заявка одобрена; на валидацию навыков: {len(pending_skills)}"
                )
            else:
                label = "Заявка одобрена"
        else:
            if was_skill_validation and was_approved:
                text = message_skill_validation_rejected(
                    note=application.decision_note, reviewer=user
                )
            else:
                text = message_application_rejected(
                    note=application.decision_note, reviewer=user
                )
            label = "Заявка отклонена"
        await sync_user_commands_http(token, application.user)
        await notify_telegram_user(
            token,
            application.user_id,
            text,
            parse_mode="HTML" if not approved else None,
        )
        if approved and application.kind is JoinKind.STAFF:
            await invite_to_staff_chat(
                token, settings.staff_chat_id, application.user_id
            )
        return _flash("/community/applications", message=label)
    except (ApplicationError, ValueError) as exc:
        return _flash("/community/applications", error=str(exc))


@router.get("/community/{telegram_id}/remove", response_class=HTMLResponse)
@router.get("/people/{telegram_id}/remove", response_class=HTMLResponse)
async def remove_confirm_page(
    telegram_id: int,
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    target = await session.get(User, telegram_id)
    if target is None:
        return _flash("/community/members", error="Участник не найден")
    return await render(
        request,
        "people_remove.html",
        user=user,
        session=session,
        community_section="members",
        target=target,
        removal_reasons=list(RemovalReason),
        error=request.query_params.get("error"),
    )


@router.post("/community/{telegram_id}/remove")
@router.post("/people/{telegram_id}/remove")
async def remove_confirm_submit(
    telegram_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStaff,
    reason: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        target = await session.get(User, telegram_id)
        if target is None:
            raise ApplicationError("Участник не найден")
        was_staff = target.staff_role is not None
        await remove_member(session, actor, target, RemovalReason(reason))
        token = settings.telegram_bot_token.get_secret_value()
        await sync_user_commands_http(token, target)
        await notify_telegram_user(
            token,
            telegram_id,
            message_member_removed(RemovalReason(reason)),
        )
        if was_staff:
            await kick_from_staff_chat(token, settings.staff_chat_id, telegram_id)
        dest = "/community/staff" if was_staff else "/community/members"
        return _flash(dest, message="Участник удалён")
    except (ApplicationError, ValueError) as exc:
        return RedirectResponse(
            f"/community/{telegram_id}/remove?error={quote(str(exc))}",
            status_code=303,
        )


@router.post("/community/{telegram_id}/adjust")
@router.post("/people/{telegram_id}/adjust")
async def people_adjust(
    telegram_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageEconomy,
    currency: Annotated[str, Form()],
    action: Annotated[str, Form()],
    amount: Annotated[int, Form()],
    reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        target = await session.get(User, telegram_id)
        if target is None:
            raise EconomyError("Участник не найден")
        grant = action == "grant"
        note = reason.strip() or ("начисление" if grant else "списание")
        key = f"admin-people:{uuid.uuid4()}"
        if currency == "respect":
            await change_respect(
                session,
                actor,
                telegram_id,
                amount,
                note,
                grant=grant,
                idempotency_key=key,
            )
            text = message_respect_changed(
                amount=amount,
                grant=grant,
                respect_after=target.respect,
            )
            label = "Респект обновлён"
        else:
            await change_balance(
                session,
                actor,
                telegram_id,
                amount,
                note,
                grant=grant,
                idempotency_key=key,
            )
            text = message_balance_changed(
                amount=amount,
                grant=grant,
            )
            label = "Благодать обновлена"
        await notify_telegram_user(
            settings.telegram_bot_token.get_secret_value(),
            telegram_id,
            text,
        )
        return _flash("/community/members", message=label)
    except (EconomyError, ValueError) as exc:
        return _flash("/community/members", error=str(exc))


@router.get("/avatar/{telegram_id}")
async def user_avatar(
    telegram_id: int,
    session: DbSession,
    settings: SettingsDep,
    _: CurrentUser,
) -> Response:
    profile = await session.get(User, telegram_id)
    if profile is None or not profile.avatar_file_id:
        return Response(status_code=404)
    try:
        content, content_type = await download_telegram_file(
            settings.telegram_bot_token.get_secret_value(),
            profile.avatar_file_id,
        )
    except TelegramProfileError:
        return Response(status_code=404)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
