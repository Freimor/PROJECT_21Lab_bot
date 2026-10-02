"""Boards, calendar, documents, and private files for staff projects."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from starlette.datastructures import UploadFile

from lab21_bot.data import role_labels
from lab21_bot.models import (
    CommunityQuest,
    Order,
    Product,
    Project,
    ProjectColumn,
    ProjectDoc,
    ProjectFile,
    ProjectFolder,
    ProjectLinkKind,
    ProjectTag,
    ProjectTask,
    ProjectTaskAssignee,
    ProjectTaskTag,
    SeasonEvent,
    StaffRole,
    User,
)
from lab21_bot.services.doc_markdown import render_markdown
from lab21_bot.services.project_storage import (
    read_private_file,
    save_private_file,
    unlink_private_file,
)
from lab21_bot.services.ranks_catalog import catalog_key
from lab21_bot.services.uploads import UploadError

DEFAULT_COLUMN_TITLES = ("Бэклог", "В работе", "Готово")
DEFAULT_TASK_COLOR = "#ff7a25"
DEFAULT_TAG_COLOR = "#6b7c93"
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_MONTH_NAMES = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
_SHORT_MONTHS = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)
_MIN_BAR_PCT = 0.85
_LINK_MODELS = {
    ProjectLinkKind.ORDER: Order,
    ProjectLinkKind.QUEST: CommunityQuest,
    ProjectLinkKind.EVENT: SeasonEvent,
}
_LINK_GROUPS = {
    ProjectLinkKind.ORDER: "Заказы",
    ProjectLinkKind.QUEST: "Квесты",
    ProjectLinkKind.EVENT: "Ивенты",
}


class ProjectError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectSummary:
    id: int
    title: str
    description: str
    task_count: int


@dataclass(frozen=True)
class PersonView:
    telegram_id: int
    full_name: str


@dataclass(frozen=True)
class TagView:
    id: int
    title: str
    color: str


@dataclass(frozen=True)
class TaskView:
    id: int
    title: str
    body: str
    color: str
    start_on: date | None
    due_on: date | None
    column_id: int
    assignees: list[PersonView]
    tags: list[TagView]
    link_value: str
    link_label: str
    link_href: str


@dataclass(frozen=True)
class ColumnView:
    id: int
    title: str
    position: int
    tasks: list[TaskView]


@dataclass(frozen=True)
class BoardView:
    project: Project
    columns: list[ColumnView]
    tags: list[TagView]
    tasks: list[TaskView]


@dataclass(frozen=True)
class LinkOption:
    value: str
    label: str
    group: str


@dataclass(frozen=True)
class TaskInput:
    title: str
    body: str
    column_id: int
    color: str
    start_on: date | None
    due_on: date | None
    assignee_ids: list[int]
    tag_ids: list[int]
    link: str


@dataclass(frozen=True)
class CalendarTask:
    id: int
    title: str
    color: str
    href: str
    hint: str


@dataclass(frozen=True)
class CalendarDay:
    date: date | None
    in_month: bool
    is_today: bool
    tasks: list[CalendarTask]


@dataclass(frozen=True)
class MonthCalendar:
    label: str
    year: int
    month: int
    weeks: list[list[CalendarDay]]


@dataclass(frozen=True)
class TimelineMonth:
    label: str
    left: float
    width: float


@dataclass(frozen=True)
class TimelineRow:
    id: int
    title: str
    project_title: str
    color: str
    href: str
    starts_on: date
    ends_on: date
    left: float
    width: float
    continues_left: bool
    continues_right: bool
    state: str


@dataclass(frozen=True)
class YearTimeline:
    year: int
    years: list[int]
    days: int
    months: list[TimelineMonth]
    today_pct: float | None
    today: date
    rows: list[TimelineRow]


@dataclass(frozen=True)
class FolderCrumb:
    id: int | None
    name: str


@dataclass(frozen=True)
class FolderItem:
    id: int
    name: str
    allowed_roles: list[str]


@dataclass(frozen=True)
class FileItem:
    id: int
    name: str
    size_label: str
    uploaded_by: str
    allowed_roles: list[str]


@dataclass(frozen=True)
class FolderPage:
    folder_id: int | None
    crumbs: list[FolderCrumb]
    folders: list[FolderItem]
    files: list[FileItem]
    current_roles: list[str]


def render_doc(source: str) -> str:
    return render_markdown(source)


def parse_color(value: str, *, default: str) -> str:
    text = value.strip()
    if not text:
        return default
    if _COLOR_RE.match(text) is None:
        raise ProjectError("Цвет задайте как #rrggbb")
    return text.lower()


def parse_day(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ProjectError("Некорректная дата") from exc


def resolve_year(raw: str | None, today: date) -> int:
    if raw and raw.strip().isdigit():
        year = int(raw.strip())
        if 2000 <= year <= 2100:
            return year
    return today.year


def resolve_month(raw: str | None, today: date) -> tuple[int, int]:
    if raw:
        match = _MONTH_RE.match(raw.strip())
        if match is not None:
            year = int(match.group(1))
            month = int(match.group(2))
            if 2000 <= year <= 2100 and 1 <= month <= 12:
                return year, month
    return today.year, today.month


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_label(year: int, month: int) -> str:
    return f"{_MONTH_NAMES[month]} {year}"


def normalize_roles(raw: list[str]) -> list[str]:
    known = set(role_labels())
    chosen: list[str] = []
    for item in raw:
        key = catalog_key(item)
        if key in known and key not in chosen:
            chosen.append(key)
    return chosen


def can_access_roles(user: User, roles: list[str]) -> bool:
    if user.staff_role is None or user.is_active is False:
        return False
    key = catalog_key(user.staff_role)
    if key == StaffRole.LORD.value:
        return True
    chosen = [catalog_key(role) for role in roles if catalog_key(role)]
    if not chosen:
        return True
    return key in chosen


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} КБ"
    return f"{size / (1024 * 1024):.1f} МБ"


def _clean_title(value: str, *, empty: str, limit: int) -> str:
    title = " ".join(value.split())
    if not title:
        raise ProjectError(empty)
    if len(title) > limit:
        raise ProjectError(f"Название длиннее {limit} символов")
    return title


def _check_dates(start_on: date | None, due_on: date | None) -> None:
    if start_on is not None and due_on is not None and start_on > due_on:
        raise ProjectError("Дата начала позже дедлайна")


async def _require_project(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise ProjectError("Проект не найден")
    return project


async def _require_column(
    session: AsyncSession, project_id: int, column_id: int
) -> ProjectColumn:
    column = await session.get(ProjectColumn, column_id)
    if column is None or column.project_id != project_id:
        raise ProjectError("Колонка не найдена")
    return column


async def _require_task(session: AsyncSession, project_id: int, task_id: int) -> ProjectTask:
    task = await session.get(ProjectTask, task_id)
    if task is None or task.project_id != project_id:
        raise ProjectError("Задача не найдена")
    return task


async def _next_task_position(session: AsyncSession, column_id: int) -> int:
    current = await session.scalar(
        select(func.max(ProjectTask.position)).where(ProjectTask.column_id == column_id)
    )
    return 0 if current is None else int(current) + 1


async def _staff_ids(session: AsyncSession, user_ids: list[int]) -> list[int]:
    unique = list(dict.fromkeys(user_ids))
    if not unique:
        return []
    found = set(
        await session.scalars(
            select(User.telegram_id).where(
                User.telegram_id.in_(unique),
                User.staff_role.is_not(None),
                User.is_active.is_(True),
            )
        )
    )
    if found != set(unique):
        raise ProjectError("Исполнитель не из сотрудников")
    return unique


async def _tag_ids(session: AsyncSession, project_id: int, tag_ids: list[int]) -> list[int]:
    unique = list(dict.fromkeys(tag_ids))
    if not unique:
        return []
    found = set(
        await session.scalars(
            select(ProjectTag.id).where(
                ProjectTag.project_id == project_id,
                ProjectTag.id.in_(unique),
            )
        )
    )
    if found != set(unique):
        raise ProjectError("Тег не из этого проекта")
    return unique


async def _apply_link(
    session: AsyncSession, task: ProjectTask, raw: str
) -> None:
    text = raw.strip()
    if not text:
        task.link_kind = None
        task.link_id = None
        return
    kind_raw, sep, id_raw = text.partition(":")
    if not sep:
        raise ProjectError("Некорректная связь")
    try:
        kind = ProjectLinkKind(kind_raw)
        link_id = int(id_raw)
    except ValueError as exc:
        raise ProjectError("Некорректная связь") from exc
    target = await session.get(_LINK_MODELS[kind], link_id)
    if target is None:
        raise ProjectError("Связанный объект не найден")
    task.link_kind = kind
    task.link_id = link_id


async def _replace_assignees(session: AsyncSession, task: ProjectTask, user_ids: list[int]) -> None:
    await session.execute(delete(ProjectTaskAssignee).where(ProjectTaskAssignee.task_id == task.id))
    for user_id in user_ids:
        session.add(ProjectTaskAssignee(task_id=task.id, user_id=user_id))


async def _replace_tags(session: AsyncSession, task: ProjectTask, tag_ids: list[int]) -> None:
    await session.execute(delete(ProjectTaskTag).where(ProjectTaskTag.task_id == task.id))
    for tag_id in tag_ids:
        session.add(ProjectTaskTag(task_id=task.id, tag_id=tag_id))


async def list_projects(session: AsyncSession) -> list[ProjectSummary]:
    projects = list(await session.scalars(select(Project).order_by(Project.title, Project.id)))
    if not projects:
        return []
    rows = await session.execute(
        select(ProjectTask.project_id, func.count())
        .group_by(ProjectTask.project_id)
    )
    counts = {project_id: int(count) for project_id, count in rows.all()}
    return [
        ProjectSummary(
            id=project.id,
            title=project.title,
            description=project.description,
            task_count=counts.get(project.id, 0),
        )
        for project in projects
    ]


async def create_project(
    session: AsyncSession,
    actor: User,
    title: str,
    description: str,
) -> Project:
    project = Project(
        title=_clean_title(title, empty="Укажите название проекта", limit=200),
        description=description.strip(),
        created_by=actor.telegram_id,
    )
    session.add(project)
    await session.flush()
    for position, column_title in enumerate(DEFAULT_COLUMN_TITLES):
        session.add(
            ProjectColumn(project_id=project.id, title=column_title, position=position)
        )
    await session.flush()
    return project


async def delete_project(session: AsyncSession, project_id: int, root: str | Path) -> None:
    await _require_project(session, project_id)
    files = list(
        await session.scalars(select(ProjectFile).where(ProjectFile.project_id == project_id))
    )
    for item in files:
        unlink_private_file(root, item.relative_path)
    task_ids = select(ProjectTask.id).where(ProjectTask.project_id == project_id)
    await session.execute(
        delete(ProjectTaskAssignee).where(ProjectTaskAssignee.task_id.in_(task_ids))
    )
    await session.execute(delete(ProjectTaskTag).where(ProjectTaskTag.task_id.in_(task_ids)))
    await session.execute(delete(ProjectTask).where(ProjectTask.project_id == project_id))
    await session.execute(delete(ProjectFile).where(ProjectFile.project_id == project_id))
    await session.execute(delete(ProjectFolder).where(ProjectFolder.project_id == project_id))
    await session.execute(delete(ProjectDoc).where(ProjectDoc.project_id == project_id))
    await session.execute(delete(ProjectTag).where(ProjectTag.project_id == project_id))
    await session.execute(delete(ProjectColumn).where(ProjectColumn.project_id == project_id))
    await session.execute(delete(Project).where(Project.id == project_id))


async def add_column(session: AsyncSession, project_id: int, title: str) -> ProjectColumn:
    await _require_project(session, project_id)
    current = await session.scalar(
        select(func.max(ProjectColumn.position)).where(ProjectColumn.project_id == project_id)
    )
    column = ProjectColumn(
        project_id=project_id,
        title=_clean_title(title, empty="Укажите название колонки", limit=120),
        position=0 if current is None else int(current) + 1,
    )
    session.add(column)
    await session.flush()
    return column


async def rename_column(
    session: AsyncSession, project_id: int, column_id: int, title: str
) -> None:
    column = await _require_column(session, project_id, column_id)
    column.title = _clean_title(title, empty="Укажите название колонки", limit=120)


async def delete_column(session: AsyncSession, project_id: int, column_id: int) -> None:
    column = await _require_column(session, project_id, column_id)
    used = await session.scalar(
        select(func.count()).select_from(ProjectTask).where(ProjectTask.column_id == column.id)
    )
    if used:
        raise ProjectError("В колонке есть задачи — перенесите их")
    await session.delete(column)


async def shift_column(
    session: AsyncSession, project_id: int, column_id: int, direction: int
) -> None:
    await _require_project(session, project_id)
    columns = list(
        await session.scalars(
            select(ProjectColumn)
            .where(ProjectColumn.project_id == project_id)
            .order_by(ProjectColumn.position, ProjectColumn.id)
        )
    )
    index = next((pos for pos, column in enumerate(columns) if column.id == column_id), None)
    if index is None:
        raise ProjectError("Колонка не найдена")
    target = index + (1 if direction > 0 else -1)
    if target < 0 or target >= len(columns):
        return
    columns[index].position, columns[target].position = (
        columns[target].position,
        columns[index].position,
    )


async def add_tag(
    session: AsyncSession, project_id: int, title: str, color: str
) -> ProjectTag:
    await _require_project(session, project_id)
    cleaned = _clean_title(title, empty="Укажите название тега", limit=64)
    exists = await session.scalar(
        select(ProjectTag.id).where(
            ProjectTag.project_id == project_id,
            ProjectTag.title == cleaned,
        )
    )
    if exists is not None:
        raise ProjectError("Тег с таким названием уже есть")
    tag = ProjectTag(
        project_id=project_id,
        title=cleaned,
        color=parse_color(color, default=DEFAULT_TAG_COLOR),
    )
    session.add(tag)
    await session.flush()
    return tag


async def delete_tag(session: AsyncSession, project_id: int, tag_id: int) -> None:
    tag = await session.get(ProjectTag, tag_id)
    if tag is None or tag.project_id != project_id:
        raise ProjectError("Тег не найден")
    await session.execute(delete(ProjectTaskTag).where(ProjectTaskTag.tag_id == tag.id))
    await session.delete(tag)


async def create_task(
    session: AsyncSession, actor: User, project_id: int, data: TaskInput
) -> ProjectTask:
    await _require_project(session, project_id)
    await _require_column(session, project_id, data.column_id)
    _check_dates(data.start_on, data.due_on)
    assignees = await _staff_ids(session, data.assignee_ids)
    tags = await _tag_ids(session, project_id, data.tag_ids)
    task = ProjectTask(
        project_id=project_id,
        column_id=data.column_id,
        title=_clean_title(data.title, empty="Укажите название задачи", limit=200),
        body=data.body.strip(),
        color=parse_color(data.color, default=DEFAULT_TASK_COLOR),
        start_on=data.start_on,
        due_on=data.due_on,
        position=await _next_task_position(session, data.column_id),
        created_by=actor.telegram_id,
    )
    await _apply_link(session, task, data.link)
    session.add(task)
    await session.flush()
    await _replace_assignees(session, task, assignees)
    await _replace_tags(session, task, tags)
    return task


async def update_task(
    session: AsyncSession, project_id: int, task_id: int, data: TaskInput
) -> None:
    task = await _require_task(session, project_id, task_id)
    await _require_column(session, project_id, data.column_id)
    _check_dates(data.start_on, data.due_on)
    assignees = await _staff_ids(session, data.assignee_ids)
    tags = await _tag_ids(session, project_id, data.tag_ids)
    if task.column_id != data.column_id:
        task.position = await _next_task_position(session, data.column_id)
    task.column_id = data.column_id
    task.title = _clean_title(data.title, empty="Укажите название задачи", limit=200)
    task.body = data.body.strip()
    task.color = parse_color(data.color, default=DEFAULT_TASK_COLOR)
    task.start_on = data.start_on
    task.due_on = data.due_on
    await _apply_link(session, task, data.link)
    await _replace_assignees(session, task, assignees)
    await _replace_tags(session, task, tags)


async def delete_task(session: AsyncSession, project_id: int, task_id: int) -> None:
    task = await _require_task(session, project_id, task_id)
    await session.delete(task)


async def move_task(
    session: AsyncSession, project_id: int, task_id: int, column_id: int
) -> None:
    task = await _require_task(session, project_id, task_id)
    await _require_column(session, project_id, column_id)
    if task.column_id == column_id:
        return
    task.column_id = column_id
    task.position = await _next_task_position(session, column_id)


async def reorder_column(
    session: AsyncSession, project_id: int, column_id: int, task_ids: list[int]
) -> None:
    await _require_column(session, project_id, column_id)
    unique = list(dict.fromkeys(task_ids))
    if not unique:
        return
    tasks = list(
        await session.scalars(
            select(ProjectTask).where(
                ProjectTask.project_id == project_id,
                ProjectTask.id.in_(unique),
            )
        )
    )
    by_id = {task.id: task for task in tasks}
    if set(by_id) != set(unique):
        raise ProjectError("Задача не из этого проекта")
    for index, task_id in enumerate(unique):
        task = by_id[task_id]
        task.column_id = column_id
        task.position = index


def _kind_value(task: ProjectTask) -> str:
    if isinstance(task.link_kind, ProjectLinkKind):
        return task.link_kind.value
    if task.link_kind is None:
        return ""
    return str(task.link_kind)


def _link_value(task: ProjectTask) -> str:
    if task.link_kind is None or task.link_id is None:
        return ""
    return f"{_kind_value(task)}:{task.link_id}"


async def _link_lookup(
    session: AsyncSession, tasks: list[ProjectTask]
) -> dict[tuple[str, int], tuple[str, str]]:
    def linked(kind: ProjectLinkKind) -> list[int]:
        return [
            task.link_id
            for task in tasks
            if task.link_kind == kind and task.link_id is not None
        ]

    order_ids = linked(ProjectLinkKind.ORDER)
    quest_ids = linked(ProjectLinkKind.QUEST)
    event_ids = linked(ProjectLinkKind.EVENT)
    found: dict[tuple[str, int], tuple[str, str]] = {}
    if order_ids:
        rows = await session.execute(
            select(Order.id, Product.name)
            .join(Product, Product.id == Order.product_id)
            .where(Order.id.in_(order_ids))
        )
        for order_id, name in rows.all():
            found[("order", int(order_id))] = (f"Заказ #{order_id} · {name}", "/shop")
    if quest_ids:
        quests = await session.scalars(
            select(CommunityQuest).where(CommunityQuest.id.in_(quest_ids))
        )
        for quest in quests:
            found[("quest", quest.id)] = (
                f"Квест #{quest.number} {quest.title}",
                f"/gamification/quests/{quest.id}",
            )
    if event_ids:
        events = await session.scalars(select(SeasonEvent).where(SeasonEvent.id.in_(event_ids)))
        for event in events:
            found[("event", event.id)] = (event.title, f"/gamification/seasons/{event.id}")
    return found


def _task_view(task: ProjectTask, links: dict[tuple[str, int], tuple[str, str]]) -> TaskView:
    kind = _kind_value(task)
    label, href = ("", "")
    if kind and task.link_id is not None:
        label, href = links.get((kind, task.link_id), ("", ""))
    return TaskView(
        id=task.id,
        title=task.title,
        body=task.body,
        color=task.color,
        start_on=task.start_on,
        due_on=task.due_on,
        column_id=task.column_id,
        assignees=[
            PersonView(telegram_id=link.user.telegram_id, full_name=link.user.full_name)
            for link in task.assignee_links
            if link.user is not None
        ],
        tags=[
            TagView(id=link.tag.id, title=link.tag.title, color=link.tag.color)
            for link in task.tag_links
            if link.tag is not None
        ],
        link_value=_link_value(task),
        link_label=label,
        link_href=href,
    )


async def _load_tasks(
    session: AsyncSession,
    project_id: int,
    *,
    assignee_id: int | None,
    tag_id: int | None,
) -> list[ProjectTask]:
    stmt = (
        select(ProjectTask)
        .where(ProjectTask.project_id == project_id)
        .options(
            selectinload(ProjectTask.assignee_links).selectinload(ProjectTaskAssignee.user),
            selectinload(ProjectTask.tag_links).selectinload(ProjectTaskTag.tag),
        )
        .order_by(ProjectTask.position, ProjectTask.id)
    )
    if assignee_id is not None:
        stmt = stmt.where(
            ProjectTask.id.in_(
                select(ProjectTaskAssignee.task_id).where(
                    ProjectTaskAssignee.user_id == assignee_id
                )
            )
        )
    if tag_id is not None:
        stmt = stmt.where(
            ProjectTask.id.in_(
                select(ProjectTaskTag.task_id).where(ProjectTaskTag.tag_id == tag_id)
            )
        )
    return list(await session.scalars(stmt))


async def load_board(
    session: AsyncSession,
    project_id: int,
    *,
    assignee_id: int | None = None,
    tag_id: int | None = None,
) -> BoardView:
    project = await _require_project(session, project_id)
    columns = list(
        await session.scalars(
            select(ProjectColumn)
            .where(ProjectColumn.project_id == project_id)
            .order_by(ProjectColumn.position, ProjectColumn.id)
        )
    )
    tags = [
        TagView(id=tag.id, title=tag.title, color=tag.color)
        for tag in await session.scalars(
            select(ProjectTag)
            .where(ProjectTag.project_id == project_id)
            .order_by(ProjectTag.title)
        )
    ]
    tasks = await _load_tasks(
        session, project_id, assignee_id=assignee_id, tag_id=tag_id
    )
    links = await _link_lookup(session, tasks)
    views = [_task_view(task, links) for task in tasks]
    by_column: dict[int, list[TaskView]] = {column.id: [] for column in columns}
    for view in views:
        by_column.setdefault(view.column_id, []).append(view)
    return BoardView(
        project=project,
        columns=[
            ColumnView(
                id=column.id,
                title=column.title,
                position=column.position,
                tasks=by_column.get(column.id, []),
            )
            for column in columns
        ],
        tags=tags,
        tasks=views,
    )


async def link_options(session: AsyncSession) -> list[LinkOption]:
    options: list[LinkOption] = []
    orders = await session.execute(
        select(Order.id, Product.name)
        .join(Product, Product.id == Order.product_id)
        .order_by(Order.id.desc())
        .limit(40)
    )
    for order_id, name in orders.all():
        options.append(
            LinkOption(
                f"order:{order_id}",
                f"#{order_id} · {name}",
                _LINK_GROUPS[ProjectLinkKind.ORDER],
            )
        )
    quests = await session.scalars(
        select(CommunityQuest).order_by(CommunityQuest.id.desc()).limit(40)
    )
    for quest in quests:
        options.append(
            LinkOption(
                f"quest:{quest.id}",
                f"#{quest.number} {quest.title}",
                _LINK_GROUPS[ProjectLinkKind.QUEST],
            )
        )
    events = await session.scalars(
        select(SeasonEvent).order_by(SeasonEvent.starts_on.desc()).limit(40)
    )
    for event in events:
        options.append(
            LinkOption(f"event:{event.id}", event.title, _LINK_GROUPS[ProjectLinkKind.EVENT])
        )
    return options


def _covers(task: ProjectTask, day: date) -> bool:
    if task.start_on is not None and task.due_on is not None:
        return task.start_on <= day <= task.due_on
    if task.start_on is not None:
        return task.start_on == day
    if task.due_on is not None:
        return task.due_on == day
    return False


def _parent_clause(parent_id: int | None) -> ColumnElement[bool]:
    if parent_id is None:
        return ProjectFolder.parent_id.is_(None)
    return ProjectFolder.parent_id == parent_id


def _overlap_clause(month_start: date, month_end: date) -> ColumnElement[bool]:
    return or_(
        (
            ProjectTask.start_on.is_not(None)
            & ProjectTask.due_on.is_not(None)
            & (ProjectTask.start_on <= month_end)
            & (ProjectTask.due_on >= month_start)
        ),
        (
            ProjectTask.start_on.is_not(None)
            & ProjectTask.due_on.is_(None)
            & (ProjectTask.start_on >= month_start)
            & (ProjectTask.start_on <= month_end)
        ),
        (
            ProjectTask.due_on.is_not(None)
            & ProjectTask.start_on.is_(None)
            & (ProjectTask.due_on >= month_start)
            & (ProjectTask.due_on <= month_end)
        ),
    )


async def month_calendar(
    session: AsyncSession,
    year: int,
    month: int,
    *,
    today: date,
    project_id: int | None = None,
    assignee_id: int | None = None,
    tag_id: int | None = None,
    href_for: str = "board",
) -> MonthCalendar:
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    stmt = (
        select(ProjectTask, Project.title)
        .join(Project, Project.id == ProjectTask.project_id)
        .where(_overlap_clause(month_start, month_end))
        .order_by(ProjectTask.start_on, ProjectTask.due_on, ProjectTask.id)
    )
    if project_id is not None:
        stmt = stmt.where(ProjectTask.project_id == project_id)
    if assignee_id is not None:
        stmt = stmt.where(
            ProjectTask.id.in_(
                select(ProjectTaskAssignee.task_id).where(
                    ProjectTaskAssignee.user_id == assignee_id
                )
            )
        )
    if tag_id is not None:
        stmt = stmt.where(
            ProjectTask.id.in_(
                select(ProjectTaskTag.task_id).where(ProjectTaskTag.tag_id == tag_id)
            )
        )
    rows = list((await session.execute(stmt)).all())
    weeks: list[list[CalendarDay]] = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        days: list[CalendarDay] = []
        for day in week:
            in_month = day.month == month
            chips: list[CalendarTask] = []
            if in_month:
                for task, project_title in rows:
                    if not _covers(task, day):
                        continue
                    href = (
                        f"#task-{task.id}"
                        if href_for == "hash"
                        else f"/projects/{task.project_id}#task-{task.id}"
                    )
                    chips.append(
                        CalendarTask(
                            id=task.id,
                            title=task.title,
                            color=task.color,
                            href=href,
                            hint=str(project_title),
                        )
                    )
            days.append(
                CalendarDay(
                    date=day,
                    in_month=in_month,
                    is_today=day == today,
                    tasks=chips,
                )
            )
        weeks.append(days)
    return MonthCalendar(label=month_label(year, month), year=year, month=month, weeks=weeks)


def _task_span(task: ProjectTask) -> tuple[date, date] | None:
    if task.start_on is not None and task.due_on is not None:
        start, end = task.start_on, task.due_on
        if end < start:
            start, end = end, start
        return start, end
    if task.start_on is not None:
        return task.start_on, task.start_on
    if task.due_on is not None:
        return task.due_on, task.due_on
    return None


def _timeline_state(start: date, end: date, today: date) -> str:
    if end < today:
        return "past"
    if start <= today <= end:
        return "active"
    return "upcoming"


async def year_timeline(
    session: AsyncSession,
    year: int,
    *,
    today: date,
    assignee_id: int | None = None,
) -> YearTimeline:
    jan1 = date(year, 1, 1)
    dec31 = date(year, 12, 31)
    days = (dec31 - jan1).days + 1
    months = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else dec31
        months.append(
            TimelineMonth(
                label=_SHORT_MONTHS[month - 1],
                left=round((start - jan1).days / days * 100, 4),
                width=round(((end - start).days + 1) / days * 100, 4),
            )
        )
    today_pct = None
    if today.year == year:
        today_pct = round(((today - jan1).days + 0.5) / days * 100, 4)

    dated = ProjectTask.start_on.is_not(None) | ProjectTask.due_on.is_not(None)
    year_stmt = select(ProjectTask.start_on, ProjectTask.due_on).where(dated)
    if assignee_id is not None:
        year_stmt = year_stmt.where(
            ProjectTask.id.in_(
                select(ProjectTaskAssignee.task_id).where(
                    ProjectTaskAssignee.user_id == assignee_id
                )
            )
        )
    years = {today.year, year}
    for start_on, due_on in (await session.execute(year_stmt)).all():
        if start_on is not None:
            years.add(start_on.year)
        if due_on is not None:
            years.add(due_on.year)

    stmt = (
        select(ProjectTask, Project.title)
        .join(Project, Project.id == ProjectTask.project_id)
        .where(_overlap_clause(jan1, dec31))
        .order_by(ProjectTask.start_on, ProjectTask.due_on, ProjectTask.id)
    )
    if assignee_id is not None:
        stmt = stmt.where(
            ProjectTask.id.in_(
                select(ProjectTaskAssignee.task_id).where(
                    ProjectTaskAssignee.user_id == assignee_id
                )
            )
        )
    rows: list[TimelineRow] = []
    for task, project_title in (await session.execute(stmt)).all():
        span = _task_span(task)
        if span is None:
            continue
        start_on, end_on = span
        vis_start = max(start_on, jan1)
        vis_end = min(end_on, dec31)
        left = (vis_start - jan1).days / days * 100
        width = max(((vis_end - vis_start).days + 1) / days * 100, _MIN_BAR_PCT)
        if left + width > 100:
            left = max(0.0, 100.0 - width)
        rows.append(
            TimelineRow(
                id=task.id,
                title=task.title,
                project_title=str(project_title),
                color=task.color,
                href=f"/projects/{task.project_id}#task-{task.id}",
                starts_on=start_on,
                ends_on=end_on,
                left=round(left, 4),
                width=round(width, 4),
                continues_left=start_on < jan1,
                continues_right=end_on > dec31,
                state=_timeline_state(start_on, end_on, today),
            )
        )
    rows.sort(key=lambda row: (row.starts_on, row.id))
    return YearTimeline(
        year=year,
        years=sorted(years),
        days=days,
        months=months,
        today_pct=today_pct,
        today=today,
        rows=rows,
    )


async def list_docs(session: AsyncSession, project_id: int) -> list[ProjectDoc]:
    await _require_project(session, project_id)
    return list(
        await session.scalars(
            select(ProjectDoc)
            .where(ProjectDoc.project_id == project_id)
            .order_by(ProjectDoc.title, ProjectDoc.id)
        )
    )


async def get_doc(session: AsyncSession, project_id: int, doc_id: int) -> ProjectDoc:
    doc = await session.get(ProjectDoc, doc_id)
    if doc is None or doc.project_id != project_id:
        raise ProjectError("Документ не найден")
    return doc


async def save_doc(
    session: AsyncSession,
    actor: User,
    project_id: int,
    title: str,
    body_md: str,
    doc_id: int | None = None,
) -> ProjectDoc:
    await _require_project(session, project_id)
    cleaned = _clean_title(title, empty="Укажите название документа", limit=200)
    if doc_id is None:
        doc = ProjectDoc(
            project_id=project_id,
            title=cleaned,
            body_md=body_md,
            updated_by=actor.telegram_id,
        )
        session.add(doc)
        await session.flush()
        return doc
    doc = await get_doc(session, project_id, doc_id)
    doc.title = cleaned
    doc.body_md = body_md
    doc.updated_by = actor.telegram_id
    return doc


async def delete_doc(session: AsyncSession, project_id: int, doc_id: int) -> None:
    doc = await get_doc(session, project_id, doc_id)
    await session.delete(doc)


def _folder_roles(folder: ProjectFolder | None) -> list[str]:
    if folder is None or not folder.allowed_roles:
        return []
    return list(folder.allowed_roles)


def _file_role_list(item: ProjectFile, folder: ProjectFolder | None) -> list[str]:
    if item.allowed_roles:
        return list(item.allowed_roles)
    return _folder_roles(folder)


def _folder_visible(user: User, folder: ProjectFolder, by_id: dict[int, ProjectFolder]) -> bool:
    current: ProjectFolder | None = folder
    seen: set[int] = set()
    while current is not None:
        if current.id in seen:
            return False
        seen.add(current.id)
        if not can_access_roles(user, list(current.allowed_roles or [])):
            return False
        parent_id = current.parent_id
        current = by_id.get(parent_id) if parent_id is not None else None
    return True


async def _folders(session: AsyncSession, project_id: int) -> list[ProjectFolder]:
    return list(
        await session.scalars(
            select(ProjectFolder)
            .where(ProjectFolder.project_id == project_id)
            .order_by(ProjectFolder.position, ProjectFolder.name, ProjectFolder.id)
        )
    )


async def _require_folder_access(
    session: AsyncSession, user: User, project_id: int, folder_id: int | None
) -> ProjectFolder | None:
    if folder_id is None:
        return None
    folders = await _folders(session, project_id)
    by_id = {folder.id: folder for folder in folders}
    folder = by_id.get(folder_id)
    if folder is None:
        raise ProjectError("Папка не найдена")
    if not _folder_visible(user, folder, by_id):
        raise ProjectError("Папка недоступна")
    return folder


async def folder_page(
    session: AsyncSession, user: User, project_id: int, folder_id: int | None
) -> FolderPage:
    await _require_project(session, project_id)
    folders = await _folders(session, project_id)
    by_id = {folder.id: folder for folder in folders}
    current = await _require_folder_access(session, user, project_id, folder_id)
    crumbs: list[FolderCrumb] = [FolderCrumb(id=None, name="Файлы")]
    if current is not None:
        chain: list[ProjectFolder] = []
        cursor: ProjectFolder | None = current
        seen: set[int] = set()
        while cursor is not None and cursor.id not in seen:
            seen.add(cursor.id)
            chain.append(cursor)
            cursor = by_id.get(cursor.parent_id) if cursor.parent_id is not None else None
        crumbs.extend(FolderCrumb(id=item.id, name=item.name) for item in reversed(chain))
    visible_folders = [
        FolderItem(id=folder.id, name=folder.name, allowed_roles=list(folder.allowed_roles or []))
        for folder in folders
        if folder.parent_id == folder_id and _folder_visible(user, folder, by_id)
    ]
    files = list(
        await session.scalars(
            select(ProjectFile)
            .where(ProjectFile.project_id == project_id, ProjectFile.folder_id == folder_id)
            .options(selectinload(ProjectFile.uploader))
            .order_by(ProjectFile.original_name, ProjectFile.id)
        )
    )
    visible_files = [
        FileItem(
            id=item.id,
            name=item.original_name,
            size_label=format_size(item.size_bytes),
            uploaded_by=item.uploader.full_name if item.uploader is not None else "",
            allowed_roles=list(item.allowed_roles or []),
        )
        for item in files
        if can_access_roles(user, _file_role_list(item, current))
    ]
    return FolderPage(
        folder_id=folder_id,
        crumbs=crumbs,
        folders=visible_folders,
        files=visible_files,
        current_roles=list(current.allowed_roles or []) if current is not None else [],
    )


async def create_folder(
    session: AsyncSession,
    user: User,
    project_id: int,
    name: str,
    parent_id: int | None,
    allowed_roles: list[str],
) -> ProjectFolder:
    await _require_folder_access(session, user, project_id, parent_id)
    cleaned = _clean_title(name, empty="Укажите название папки", limit=160)
    exists = await session.scalar(
        select(ProjectFolder.id).where(
            ProjectFolder.project_id == project_id,
            _parent_clause(parent_id),
            ProjectFolder.name == cleaned,
        )
    )
    if exists is not None:
        raise ProjectError("Папка с таким названием уже есть")
    current = await session.scalar(
        select(func.max(ProjectFolder.position)).where(
            ProjectFolder.project_id == project_id,
            _parent_clause(parent_id),
        )
    )
    folder = ProjectFolder(
        project_id=project_id,
        parent_id=parent_id,
        name=cleaned,
        position=0 if current is None else int(current) + 1,
        allowed_roles=normalize_roles(allowed_roles),
    )
    session.add(folder)
    await session.flush()
    return folder


async def update_folder_roles(
    session: AsyncSession,
    user: User,
    project_id: int,
    folder_id: int,
    allowed_roles: list[str],
) -> None:
    folder = await _require_folder_access(session, user, project_id, folder_id)
    if folder is None:
        raise ProjectError("Папка не найдена")
    folder.allowed_roles = normalize_roles(allowed_roles)


def _descendant_ids(folders: list[ProjectFolder], root_id: int) -> list[int]:
    children: dict[int | None, list[int]] = {}
    for folder in folders:
        children.setdefault(folder.parent_id, []).append(folder.id)
    found: list[int] = []
    stack = [root_id]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        found.append(current)
        stack.extend(children.get(current, []))
    return found


async def delete_folder(
    session: AsyncSession, user: User, project_id: int, folder_id: int, root: str | Path
) -> None:
    await _require_folder_access(session, user, project_id, folder_id)
    folders = await _folders(session, project_id)
    ids = _descendant_ids(folders, folder_id)
    files = list(
        await session.scalars(select(ProjectFile).where(ProjectFile.folder_id.in_(ids)))
    )
    for item in files:
        unlink_private_file(root, item.relative_path)
    if files:
        file_ids = [item.id for item in files]
        await session.execute(delete(ProjectFile).where(ProjectFile.id.in_(file_ids)))
    remaining = set(ids)
    parent_of = {folder.id: folder.parent_id for folder in folders}
    while remaining:
        leaves = [
            item
            for item in remaining
            if not any(parent_of.get(other) == item for other in remaining)
        ]
        if not leaves:
            leaves = list(remaining)
        await session.execute(delete(ProjectFolder).where(ProjectFolder.id.in_(leaves)))
        remaining -= set(leaves)


async def store_file(
    session: AsyncSession,
    user: User,
    project_id: int,
    folder_id: int | None,
    upload: UploadFile,
    root: str | Path,
    allowed_roles: list[str],
) -> ProjectFile:
    await _require_folder_access(session, user, project_id, folder_id)
    try:
        relative, original, content_type, size = await save_private_file(root, project_id, upload)
    except UploadError as exc:
        raise ProjectError(str(exc)) from exc
    item = ProjectFile(
        project_id=project_id,
        folder_id=folder_id,
        original_name=original,
        relative_path=relative,
        content_type=content_type,
        size_bytes=size,
        uploaded_by=user.telegram_id,
        allowed_roles=normalize_roles(allowed_roles),
    )
    session.add(item)
    await session.flush()
    return item


async def update_file_roles(
    session: AsyncSession,
    user: User,
    project_id: int,
    file_id: int,
    allowed_roles: list[str],
) -> None:
    item = await _readable_file(session, user, project_id, file_id)
    item.allowed_roles = normalize_roles(allowed_roles)


async def delete_stored_file(
    session: AsyncSession, user: User, project_id: int, file_id: int, root: str | Path
) -> None:
    item = await _readable_file(session, user, project_id, file_id)
    unlink_private_file(root, item.relative_path)
    await session.delete(item)


async def _readable_file(
    session: AsyncSession, user: User, project_id: int, file_id: int
) -> ProjectFile:
    item = await session.get(ProjectFile, file_id)
    if item is None or item.project_id != project_id:
        raise ProjectError("Файл не найден")
    folder = await _require_folder_access(session, user, project_id, item.folder_id)
    if not can_access_roles(user, _file_role_list(item, folder)):
        raise ProjectError("Файл недоступен")
    return item


async def read_stored_file(
    session: AsyncSession, user: User, project_id: int, file_id: int, root: str | Path
) -> tuple[ProjectFile, bytes]:
    item = await _readable_file(session, user, project_id, file_id)
    try:
        payload = read_private_file(root, item.relative_path)
    except UploadError as exc:
        raise ProjectError(str(exc)) from exc
    return item, payload
