from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from lab21_bot.admin.deps import CurrentUser, DbSession, RequireManageEconomy, RequireManageStaff, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.models import JoinApplication, JoinKind, RemovalReason, StaffRole, User
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
    list_community_members,
    list_pending_applications,
    remove_member,
    resolve_application,
)
from lab21_bot.services.commands import sync_user_commands_http
from lab21_bot.services.economy import EconomyError, change_balance, change_respect
from lab21_bot.services.notify import notify_telegram_user
from lab21_bot.services.telegram_profile import (
    TelegramProfileError,
    download_telegram_file,
    sync_users_profiles,
)

router = APIRouter(tags=["people"])


@router.get("/people", response_class=HTMLResponse)
async def people_page(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> HTMLResponse:
    can_staff = has_permission(user, Permission.MANAGE_STAFF)
    can_economy = has_permission(user, Permission.MANAGE_ECONOMY)
    if not can_staff and not can_economy:
        return RedirectResponse("/", status_code=303)
    staff = await list_staff(session) if can_staff else []
    members = await list_community_members(session)
    applications = await list_pending_applications(session) if can_staff else []
    profiles = (
        staff
        + members
        + [item.user for item in applications if item.user is not None]
    )
    await sync_users_profiles(
        session,
        profiles,
        settings.telegram_bot_token.get_secret_value(),
    )
    return render(
        request,
        "people.html",
        user=user,
        staff=staff,
        members=members,
        applications=applications,
        roles=list(StaffRole),
        removal_reasons=list(RemovalReason),
        can_staff=can_staff,
        can_economy=can_economy,
        message=request.query_params.get("message"),
        error=request.query_params.get("error"),
    )


@router.get("/staff", response_class=HTMLResponse)
@router.get("/adepts", response_class=HTMLResponse)
async def people_legacy_redirect() -> RedirectResponse:
    return RedirectResponse("/people", status_code=303)


@router.post("/people/set-role")
async def set_role(
    session: DbSession,
    actor: RequireManageStaff,
    target_query: Annotated[str, Form()],
    role: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        target = await find_user(session, target_query)
        if target is None:
            raise AccessDenied("Участник не найден")
        new_role = None if role in {"", "none"} else StaffRole(role)
        await set_staff_role(session, actor, target, new_role)
        if new_role is not None:
            target.balance = 0
            target.respect = 0
        return RedirectResponse("/people?message=" + quote("Роль обновлена"), status_code=303)
    except (AccessDenied, ValueError) as exc:
        return RedirectResponse(f"/people?error={quote(str(exc))}", status_code=303)


@router.post("/people/applications/{application_id}/resolve")
async def resolve_people_application(
    application_id: int,
    session: DbSession,
    settings: SettingsDep,
    actor: RequireManageStaff,
    approve: Annotated[str, Form()],
    staff_role: Annotated[str, Form()] = "watcher",
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        approved = approve.lower() in {"1", "true", "yes"}
        existing = await session.get(JoinApplication, application_id)
        if existing is None:
            raise ApplicationError("Заявка не найдена")
        role = None
        if approved and existing.kind is JoinKind.STAFF:
            role = StaffRole(staff_role)
        application = await resolve_application(
            session,
            actor,
            application_id,
            approve=approved,
            staff_role=role,
            note=note.strip() or None,
        )
        token = settings.telegram_bot_token.get_secret_value()
        if approved:
            if application.user.staff_role is not None:
                role_label = {
                    StaffRole.LORD: "Лорд",
                    StaffRole.MAGISTER: "Магистр",
                    StaffRole.TECH_PRIEST: "Техножрец",
                    StaffRole.WATCHER: "Смотрящий",
                }[application.user.staff_role]
                text = (
                    f"Заявка сотрудника одобрена. Роль: {role_label}.\n"
                    "Откройте /start или /menu."
                )
            else:
                text = (
                    "Заявка послушника одобрена. Добро пожаловать в Lab21.\n"
                    "Откройте /start или /menu."
                )
        else:
            text = "Заявка отклонена."
        await sync_user_commands_http(token, application.user)
        await notify_telegram_user(token, application.user_id, text)
        label = "Заявка одобрена" if approved else "Заявка отклонена"
        return RedirectResponse(f"/people?message={quote(label)}", status_code=303)
    except (ApplicationError, ValueError) as exc:
        return RedirectResponse(f"/people?error={quote(str(exc))}", status_code=303)


@router.get("/people/{telegram_id}/remove", response_class=HTMLResponse)
async def remove_confirm_page(
    telegram_id: int,
    request: Request,
    session: DbSession,
    user: RequireManageStaff,
) -> HTMLResponse:
    target = await session.get(User, telegram_id)
    if target is None:
        return RedirectResponse(
            f"/people?error={quote('Участник не найден')}",
            status_code=303,
        )
    return render(
        request,
        "people_remove.html",
        user=user,
        target=target,
        removal_reasons=list(RemovalReason),
        error=request.query_params.get("error"),
    )


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
        await remove_member(session, actor, target, RemovalReason(reason))
        token = settings.telegram_bot_token.get_secret_value()
        await sync_user_commands_http(token, target)
        await notify_telegram_user(
            token,
            telegram_id,
            "Вас исключили из Lab21. При повторной заявке причина удаления будет видна в админке.",
        )
        return RedirectResponse("/people?message=" + quote("Участник удалён"), status_code=303)
    except (ApplicationError, ValueError) as exc:
        return RedirectResponse(
            f"/people/{telegram_id}/remove?error={quote(str(exc))}",
            status_code=303,
        )


@router.post("/people/{telegram_id}/adjust")
async def people_adjust(
    telegram_id: int,
    session: DbSession,
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
            label = "Благодать обновлена"
        return RedirectResponse(f"/people?message={quote(label)}", status_code=303)
    except (EconomyError, ValueError) as exc:
        return RedirectResponse(f"/people?error={quote(str(exc))}", status_code=303)


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
