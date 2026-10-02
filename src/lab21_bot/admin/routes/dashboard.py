from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

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
from lab21_bot.services.projects import resolve_year, year_timeline
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
    today = datetime.now(settings.tz).date()
    year = resolve_year(request.query_params.get("year"), today)
    cal_assignee = request.query_params.get("cal_assignee") or ""
    assignee_id = user.telegram_id if cal_assignee == "me" else None
    task_timeline = await year_timeline(
        session,
        year,
        today=today,
        assignee_id=assignee_id,
    )

    def page_url(map_year: int, assignee: str) -> str:
        parts = [
            f"new={quote(new_period)}",
            f"journal_period={quote(journal_period)}",
            f"year={map_year}",
        ]
        if date_from:
            parts.append(f"from={quote(date_from)}")
        if date_to:
            parts.append(f"to={quote(date_to)}")
        if assignee:
            parts.append(f"cal_assignee={quote(assignee)}")
        return "/?" + "&".join(parts)

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
        task_timeline=task_timeline,
        year_prev=page_url(year - 1, cal_assignee),
        year_next=page_url(year + 1, cal_assignee),
        year_links={item: page_url(item, cal_assignee) for item in task_timeline.years},
        cal_all=page_url(year, ""),
        cal_mine=page_url(year, "me"),
        cal_assignee=cal_assignee,
    )
