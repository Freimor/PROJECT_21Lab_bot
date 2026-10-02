from __future__ import annotations

import io
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lab21_bot.admin.app import create_app
from lab21_bot.admin.deps import get_settings, require_user
from lab21_bot.config import Settings
from lab21_bot.db import create_engine, create_session_factory
from lab21_bot.models import Base, ProjectColumn, StaffRole, User
from lab21_bot.services.doc_markdown import render_markdown
from lab21_bot.services.project_storage import read_private_file
from lab21_bot.services.projects import (
    ProjectError,
    TaskInput,
    add_tag,
    can_access_roles,
    create_folder,
    create_project,
    create_task,
    folder_page,
    month_calendar,
    move_task,
    read_stored_file,
    save_doc,
    store_file,
    year_timeline,
)
from lab21_bot.services.uploads import UploadError


def _user(telegram_id: int, name: str, role: StaffRole) -> User:
    return User(telegram_id=telegram_id, full_name=name, staff_role=role, is_approved=True)


def _task(column_id: int, **overrides: object) -> TaskInput:
    payload: dict[str, object] = {
        "title": "Лампа",
        "body": "",
        "column_id": column_id,
        "color": "#ff7a25",
        "start_on": None,
        "due_on": None,
        "assignee_ids": [],
        "tag_ids": [],
        "link": "",
    }
    payload.update(overrides)
    return TaskInput(**payload)  # type: ignore[arg-type]


async def _columns(session: AsyncSession, project_id: int) -> list[ProjectColumn]:
    return list(
        await session.scalars(
            select(ProjectColumn)
            .where(ProjectColumn.project_id == project_id)
            .order_by(ProjectColumn.position, ProjectColumn.id)
        )
    )


async def test_create_project_starts_with_default_columns(session: AsyncSession) -> None:
    actor = _user(1, "Лорд", StaffRole.LORD)
    session.add(actor)
    await session.flush()
    project = await create_project(session, actor, "Лаба", "внутренние задачи")
    columns = await _columns(session, project.id)
    assert [column.title for column in columns] == ["Бэклог", "В работе", "Готово"]


async def test_task_keeps_tag_assignee_and_moves_column(session: AsyncSession) -> None:
    actor = _user(1, "Лорд", StaffRole.LORD)
    engineer = _user(2, "Инженер", StaffRole.TECH_PRIEST)
    session.add_all([actor, engineer])
    await session.flush()
    project = await create_project(session, actor, "Лаба", "")
    columns = await _columns(session, project.id)
    tag = await add_tag(session, project.id, "Hardware", "#c47b2b")
    task = await create_task(
        session,
        actor,
        project.id,
        _task(
            columns[0].id,
            assignee_ids=[engineer.telegram_id],
            tag_ids=[tag.id],
            start_on=date(2026, 9, 1),
            due_on=date(2026, 9, 3),
        ),
    )
    await session.refresh(task, attribute_names=["assignee_links", "tag_links"])
    assert [link.user_id for link in task.assignee_links] == [engineer.telegram_id]
    assert [link.tag_id for link in task.tag_links] == [tag.id]

    await move_task(session, project.id, task.id, columns[1].id)
    await session.refresh(task)
    assert task.column_id == columns[1].id


async def test_calendar_shows_task_on_each_day_of_range(session: AsyncSession) -> None:
    actor = _user(1, "Лорд", StaffRole.LORD)
    session.add(actor)
    await session.flush()
    project = await create_project(session, actor, "Лаба", "")
    columns = await _columns(session, project.id)
    await create_task(
        session,
        actor,
        project.id,
        _task(columns[0].id, start_on=date(2026, 9, 1), due_on=date(2026, 9, 3)),
    )
    calendar_view = await month_calendar(
        session,
        2026,
        9,
        today=date(2026, 9, 25),
        project_id=project.id,
    )
    by_day = {
        day.date.day: [item.title for item in day.tasks]
        for week in calendar_view.weeks
        for day in week
        if day.in_month and day.date is not None
    }
    assert by_day[1] == ["Лампа"]
    assert by_day[2] == ["Лампа"]
    assert by_day[3] == ["Лампа"]
    assert by_day[4] == []


async def test_year_timeline_places_task_on_its_span(session: AsyncSession) -> None:
    actor = _user(1, "Лорд", StaffRole.LORD)
    session.add(actor)
    await session.flush()
    project = await create_project(session, actor, "Лаба", "")
    columns = await _columns(session, project.id)
    await create_task(
        session,
        actor,
        project.id,
        _task(columns[0].id, start_on=date(2026, 8, 13), due_on=date(2026, 8, 15)),
    )
    timeline = await year_timeline(session, 2026, today=date(2026, 9, 25))
    assert timeline.today_pct is not None
    assert [row.title for row in timeline.rows] == ["Лампа"]
    row = timeline.rows[0]
    assert row.starts_on == date(2026, 8, 13)
    assert row.ends_on == date(2026, 8, 15)
    assert row.state == "past"
    assert row.project_title == "Лаба"
    assert timeline.months[7].label == "авг"
    assert row.left >= timeline.months[7].left
    assert row.left < timeline.months[8].left
    empty = await year_timeline(session, 2025, today=date(2026, 9, 25))
    assert empty.rows == []
    assert empty.today_pct is None


async def test_doc_markdown_strips_raw_html(session: AsyncSession) -> None:
    actor = _user(1, "Лорд", StaffRole.LORD)
    session.add(actor)
    await session.flush()
    project = await create_project(session, actor, "Лаба", "")
    doc = await save_doc(
        session,
        actor,
        project.id,
        "Заметка",
        "привет **жирный**\n\n<script>alert(1)</script>",
    )
    html = render_markdown(doc.body_md)
    assert "<script" not in html.lower()
    assert "жирный" in html
    assert "<strong>" in html


def test_private_file_rejects_parent_path(tmp_path) -> None:
    with pytest.raises(UploadError, match="путь"):
        read_private_file(tmp_path, "../secrets.txt")


def test_role_list_hides_file_from_other_staff() -> None:
    lord = _user(1, "Лорд", StaffRole.LORD)
    watcher = _user(2, "Смотрящий", StaffRole.WATCHER)
    assert can_access_roles(lord, ["lord"]) is True
    assert can_access_roles(watcher, ["lord"]) is False
    assert can_access_roles(watcher, []) is True


async def test_folder_roles_block_download(session: AsyncSession, tmp_path) -> None:
    lord = _user(1, "Лорд", StaffRole.LORD)
    watcher = _user(2, "Смотрящий", StaffRole.WATCHER)
    session.add_all([lord, watcher])
    await session.flush()
    project = await create_project(session, lord, "Лаба", "")
    folder = await create_folder(session, lord, project.id, "Секреты", None, ["lord"])
    stored = await store_file(
        session,
        lord,
        project.id,
        folder.id,
        UploadFile(filename="note.txt", file=io.BytesIO(b"secret")),
        tmp_path,
        [],
    )
    visible = await folder_page(session, watcher, project.id, None)
    assert [item.name for item in visible.folders] == []
    with pytest.raises(ProjectError, match="недоступ"):
        await read_stored_file(session, watcher, project.id, stored.id, tmp_path)
    item, payload = await read_stored_file(session, lord, project.id, stored.id, tmp_path)
    assert item.original_name == "note.txt"
    assert payload == b"secret"


def _admin_settings(tmp_path) -> Settings:
    return Settings(
        telegram_bot_token=SecretStr("999:TESTTOKEN"),
        bootstrap_magister_id=42,
        main_channel_id=-1001,
        staff_chat_id=-1002,
        database_url="sqlite+aiosqlite:///:memory:",
        admin_base_url="http://test",
        upload_dir=str(tmp_path / "uploads"),
        project_files_dir=str(tmp_path / "files"),
    )


async def test_file_download_requires_staff_session(tmp_path) -> None:
    settings = _admin_settings(tmp_path)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/projects/1/files/1")
    await engine.dispose()
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


async def test_project_pages_render(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("lab21_bot.admin.routes.dashboard.sync_user_profile", noop)
    settings = _admin_settings(tmp_path)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        actor = _user(7, "Лорд", StaffRole.LORD)
        session.add(actor)
        await session.flush()
        project = await create_project(session, actor, "Лаба", "описание")
        columns = await _columns(session, project.id)
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        await create_task(
            session,
            actor,
            project.id,
            _task(columns[0].id, start_on=today, due_on=today),
        )
        folder = await create_folder(session, actor, project.id, "Чертежи", None, [])
        await session.commit()
        project_id = project.id
        folder_id = folder.id
        staff = actor

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[require_user] = lambda: staff
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        board = await client.get(f"/projects/{project_id}")
        planner = await client.get(f"/projects/{project_id}/planner")
        docs = await client.get(f"/projects/{project_id}/docs")
        files = await client.get(f"/projects/{project_id}/files?folder={folder_id}")
        home = await client.get("/")
        projects_index = await client.get("/projects", follow_redirects=False)
    await engine.dispose()
    assert board.status_code == 200
    assert "Бэклог" in board.text
    assert "Лампа" in board.text
    assert planner.status_code == 200
    assert "Лампа" in planner.text
    assert docs.status_code == 200
    assert "Новый документ" in docs.text
    assert files.status_code == 200
    assert "Чертежи" in files.text
    assert home.status_code == 200
    assert "Лампа" in home.text
    assert "Карта года" in home.text
    assert "янв" in home.text
    assert projects_index.status_code == 303
    assert projects_index.headers["location"].endswith(f"/projects/{project_id}")
    assert "Бэклог" in board.text
    assert 'class="board"' in board.text
