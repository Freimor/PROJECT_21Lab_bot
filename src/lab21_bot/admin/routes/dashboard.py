from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from lab21_bot.admin.deps import CurrentUser, DbSession, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.services.journal import recent_journal
from lab21_bot.services.stats import dashboard_stats
from lab21_bot.services.telegram_profile import sync_user_profile

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> HTMLResponse:
    await sync_user_profile(
        session,
        user,
        settings.telegram_bot_token.get_secret_value(),
    )
    stats = await dashboard_stats(session)
    journal = await recent_journal(session)
    return render(request, "dashboard.html", user=user, stats=stats, journal=journal)
