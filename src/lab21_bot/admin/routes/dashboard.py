from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from lab21_bot.admin.deps import CurrentUser, DbSession, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.services.journal import recent_journal
from lab21_bot.services.periods import (
    PERIOD_KEYS,
    PERIOD_LABELS,
    parse_date_bound,
    parse_period,
    period_since,
)
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
    new_period = parse_period(request.query_params.get("new"), default="week")
    new_since = period_since(new_period, tz=settings.tz)

    journal_period = parse_period(request.query_params.get("journal_period"), default="all")
    date_from = request.query_params.get("from")
    date_to = request.query_params.get("to")
    since = parse_date_bound(date_from)
    until = parse_date_bound(date_to, end_of_day=True)
    if since is None and until is None and journal_period != "all":
        since = period_since(journal_period, tz=settings.tz)

    stats = await dashboard_stats(session, new_members_since=new_since)
    journal = await recent_journal(session, limit=80, since=since, until=until)
    return await render(
        request,
        "dashboard.html",
        user=user,
        session=session,
        stats=stats,
        journal=journal,
        new_period=new_period,
        period_keys=PERIOD_KEYS,
        period_labels=PERIOD_LABELS,
        journal_period=journal_period,
        date_from=date_from or "",
        date_to=date_to or "",
    )
