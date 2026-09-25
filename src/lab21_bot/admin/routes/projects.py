from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import FormData, UploadFile

from lab21_bot.admin.deps import CurrentUser, DbSession, SettingsDep
from lab21_bot.admin.templating import render
from lab21_bot.models import User
from lab21_bot.services.access import list_staff
from lab21_bot.services.projects import (
    ProjectError,
    TaskInput,
    add_column,
    add_tag,
    create_folder,
    create_project,
    create_task,
    delete_column,
    delete_doc,
    delete_folder,
    delete_project,
    delete_stored_file,
    delete_tag,
    delete_task,
    folder_page,
    get_doc,
    link_options,
    list_docs,
    list_projects,
    load_board,
    month_calendar,
    move_task,
    parse_day,
    read_stored_file,
    rename_column,
    render_doc,
    reorder_column,
    resolve_month,
    save_doc,
    shift_column,
    shift_month,
    store_file,
    update_file_roles,
    update_folder_roles,
    update_task,
)

router = APIRouter(tags=["projects"])


def _redirect(
    path: str, *, message: str | None = None, error: str | None = None
) -> RedirectResponse:
    if error:
        return RedirectResponse(f"{path}?error={quote(error)}", status_code=303)
    if message:
        return RedirectResponse(f"{path}?message={quote(message)}", status_code=303)
    return RedirectResponse(path, status_code=303)


def _message(request: Request) -> str | None:
    return request.query_params.get("message")


def _error(request: Request) -> str | None:
    return request.query_params.get("error")


def _form_str(form: FormData, key: str) -> str:
    value = form.get(key)
    return value if isinstance(value, str) else ""


def _form_ints(form: FormData, key: str) -> list[int]:
    chosen: list[int] = []
    for item in form.getlist(key):
        if isinstance(item, str) and item.isdigit():
            chosen.append(int(item))
    return chosen


def _form_roles(form: FormData) -> list[str]:
    return [item for item in form.getlist("allowed_role") if isinstance(item, str)]


def _task_input(form: FormData) -> TaskInput:
    column_raw = _form_str(form, "column_id")
    if not column_raw.isdigit():
        raise ProjectError("Выберите колонку")
    return TaskInput(
        title=_form_str(form, "title"),
        body=_form_str(form, "body"),
        column_id=int(column_raw),
        color=_form_str(form, "color"),
        start_on=parse_day(_form_str(form, "start_on")),
        due_on=parse_day(_form_str(form, "due_on")),
        assignee_ids=_form_ints(form, "assignee_id"),
        tag_ids=_form_ints(form, "tag_id"),
        link=_form_str(form, "link"),
    )


def _assignee_filter(raw: str, user: User) -> int | None:
    if raw == "me":
        return user.telegram_id
    if raw.isdigit():
        return int(raw)
    return None


def _with_query(path: str, **params: str) -> str:
    pairs = [f"{key}={quote(value)}" for key, value in params.items() if value]
    if not pairs:
        return path
    join = "&" if "?" in path else "?"
    return f"{path}{join}{'&'.join(pairs)}"


def _board_path(project_id: int, request: Request) -> str:
    return _with_query(
        f"/projects/{project_id}",
        assignee=request.query_params.get("assignee") or "",
        tag=request.query_params.get("tag") or "",
    )


def _not_found(exc: ProjectError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/projects", response_class=HTMLResponse)
async def projects_page(
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    return await render(
        request,
        "projects.html",
        user=user,
        session=session,
        projects=await list_projects(session),
        message=_message(request),
        error=_error(request),
    )


@router.post("/projects")
async def projects_create(
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    try:
        project = await create_project(
            session,
            user,
            _form_str(form, "title"),
            _form_str(form, "description"),
        )
    except ProjectError as exc:
        return _redirect("/projects", error=str(exc))
    return _redirect(f"/projects/{project.id}", message="Проект создан")


@router.post("/projects/{project_id}/delete")
async def projects_delete(
    project_id: int,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> RedirectResponse:
    try:
        await delete_project(session, project_id, settings.project_files_dir)
    except ProjectError as exc:
        return _redirect("/projects", error=str(exc))
    return _redirect("/projects", message="Проект удалён")


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_board(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    assignee_raw = request.query_params.get("assignee") or ""
    tag_raw = request.query_params.get("tag") or ""
    tag_id = int(tag_raw) if tag_raw.isdigit() else None
    try:
        board = await load_board(
            session,
            project_id,
            assignee_id=_assignee_filter(assignee_raw, user),
            tag_id=tag_id,
        )
        options = await link_options(session)
        staff = await list_staff(session)
    except ProjectError as exc:
        raise _not_found(exc) from exc
    return await render(
        request,
        "project_board.html",
        user=user,
        session=session,
        project=board.project,
        board=board,
        staff=staff,
        link_options=options,
        assignee=assignee_raw,
        tag=tag_raw,
        sortable=not assignee_raw and not tag_raw,
        message=_message(request),
        error=_error(request),
    )


@router.post("/projects/{project_id}/columns")
async def project_column_add(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    try:
        await add_column(session, project_id, _form_str(form, "title"))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Колонка добавлена")


@router.post("/projects/{project_id}/columns/{column_id}")
async def project_column_rename(
    project_id: int,
    column_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    try:
        await rename_column(session, project_id, column_id, _form_str(form, "title"))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Колонка обновлена")


@router.post("/projects/{project_id}/columns/{column_id}/delete")
async def project_column_delete(
    project_id: int,
    column_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    path = _board_path(project_id, request)
    try:
        await delete_column(session, project_id, column_id)
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Колонка удалена")


@router.post("/projects/{project_id}/columns/{column_id}/shift")
async def project_column_shift(
    project_id: int,
    column_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    direction = -1 if _form_str(form, "direction") == "-1" else 1
    try:
        await shift_column(session, project_id, column_id, direction)
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path)


@router.post("/projects/{project_id}/tags")
async def project_tag_add(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    try:
        await add_tag(session, project_id, _form_str(form, "title"), _form_str(form, "color"))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Тег добавлен")


@router.post("/projects/{project_id}/tags/{tag_id}/delete")
async def project_tag_delete(
    project_id: int,
    tag_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    path = _board_path(project_id, request)
    try:
        await delete_tag(session, project_id, tag_id)
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Тег удалён")


@router.post("/projects/{project_id}/tasks")
async def project_task_create(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    try:
        await create_task(session, user, project_id, _task_input(form))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Задача создана")


@router.post("/projects/{project_id}/tasks/reorder")
async def project_tasks_reorder(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> Response:
    form = await request.form()
    column_raw = _form_str(form, "column_id")
    if not column_raw.isdigit():
        return Response("Выберите колонку", status_code=400)
    try:
        await reorder_column(session, project_id, int(column_raw), _form_ints(form, "task_id"))
    except ProjectError as exc:
        return Response(str(exc), status_code=400)
    return Response(status_code=204)


@router.post("/projects/{project_id}/tasks/{task_id}")
async def project_task_update(
    project_id: int,
    task_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    try:
        await update_task(session, project_id, task_id, _task_input(form))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Задача сохранена")


@router.post("/projects/{project_id}/tasks/{task_id}/delete")
async def project_task_delete(
    project_id: int,
    task_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    path = _board_path(project_id, request)
    try:
        await delete_task(session, project_id, task_id)
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Задача удалена")


@router.post("/projects/{project_id}/tasks/{task_id}/move")
async def project_task_move(
    project_id: int,
    task_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _board_path(project_id, request)
    column_raw = _form_str(form, "column_id")
    if not column_raw.isdigit():
        return _redirect(path, error="Выберите колонку")
    try:
        await move_task(session, project_id, task_id, int(column_raw))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Задача перенесена")


@router.get("/projects/{project_id}/planner", response_class=HTMLResponse)
async def project_planner(
    project_id: int,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> HTMLResponse:
    today = datetime.now(settings.tz).date()
    year, month = resolve_month(request.query_params.get("month"), today)
    assignee_raw = request.query_params.get("assignee") or ""
    tag_raw = request.query_params.get("tag") or ""
    tag_id = int(tag_raw) if tag_raw.isdigit() else None
    try:
        board = await load_board(
            session,
            project_id,
            assignee_id=_assignee_filter(assignee_raw, user),
            tag_id=tag_id,
        )
        calendar_view = await month_calendar(
            session,
            year,
            month,
            today=today,
            project_id=project_id,
            assignee_id=_assignee_filter(assignee_raw, user),
            tag_id=tag_id,
            href_for="hash",
        )
        options = await link_options(session)
        staff = await list_staff(session)
    except ProjectError as exc:
        raise _not_found(exc) from exc
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    return await render(
        request,
        "project_planner.html",
        user=user,
        session=session,
        project=board.project,
        board=board,
        staff=staff,
        link_options=options,
        assignee=assignee_raw,
        tag=tag_raw,
        task_calendar=calendar_view,
        cal_prev=_with_query(
            f"/projects/{project_id}/planner",
            month=f"{prev_year:04d}-{prev_month:02d}",
            assignee=assignee_raw,
            tag=tag_raw,
        ),
        cal_next=_with_query(
            f"/projects/{project_id}/planner",
            month=f"{next_year:04d}-{next_month:02d}",
            assignee=assignee_raw,
            tag=tag_raw,
        ),
        message=_message(request),
        error=_error(request),
    )


@router.get("/projects/{project_id}/docs", response_class=HTMLResponse)
async def project_docs(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    return await _docs_page(request, session, user, project_id, None)


@router.get("/projects/{project_id}/docs/{doc_id}", response_class=HTMLResponse)
async def project_doc(
    project_id: int,
    doc_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    return await _docs_page(request, session, user, project_id, doc_id)


async def _docs_page(
    request: Request,
    session: DbSession,
    user: User,
    project_id: int,
    doc_id: int | None,
) -> HTMLResponse:
    try:
        board = await load_board(session, project_id)
        docs = await list_docs(session, project_id)
        current = await get_doc(session, project_id, doc_id) if doc_id is not None else None
    except ProjectError as exc:
        raise _not_found(exc) from exc
    return await render(
        request,
        "project_docs.html",
        user=user,
        session=session,
        project=board.project,
        docs=docs,
        current=current,
        doc_html=render_doc(current.body_md) if current is not None else "",
        message=_message(request),
        error=_error(request),
    )


@router.post("/projects/{project_id}/docs")
async def project_doc_create(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    try:
        doc = await save_doc(
            session,
            user,
            project_id,
            _form_str(form, "title"),
            _form_str(form, "body_md"),
        )
    except ProjectError as exc:
        return _redirect(f"/projects/{project_id}/docs", error=str(exc))
    return _redirect(f"/projects/{project_id}/docs/{doc.id}", message="Документ создан")


@router.post("/projects/{project_id}/docs/{doc_id}")
async def project_doc_update(
    project_id: int,
    doc_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = f"/projects/{project_id}/docs/{doc_id}"
    try:
        await save_doc(
            session,
            user,
            project_id,
            _form_str(form, "title"),
            _form_str(form, "body_md"),
            doc_id,
        )
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Документ сохранён")


@router.post("/projects/{project_id}/docs/{doc_id}/delete")
async def project_doc_delete(
    project_id: int,
    doc_id: int,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    try:
        await delete_doc(session, project_id, doc_id)
    except ProjectError as exc:
        return _redirect(f"/projects/{project_id}/docs", error=str(exc))
    return _redirect(f"/projects/{project_id}/docs", message="Документ удалён")


def _files_path(project_id: int, folder_id: int | None) -> str:
    if folder_id is None:
        return f"/projects/{project_id}/files"
    return f"/projects/{project_id}/files?folder={folder_id}"


@router.get("/projects/{project_id}/files", response_class=HTMLResponse)
async def project_files(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> HTMLResponse:
    folder_raw = request.query_params.get("folder") or ""
    folder_id = int(folder_raw) if folder_raw.isdigit() else None
    try:
        board = await load_board(session, project_id)
        page = await folder_page(session, user, project_id, folder_id)
    except ProjectError as exc:
        raise _not_found(exc) from exc
    return await render(
        request,
        "project_files.html",
        user=user,
        session=session,
        project=board.project,
        page=page,
        message=_message(request),
        error=_error(request),
    )


@router.post("/projects/{project_id}/folders")
async def project_folder_create(
    project_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    parent_raw = _form_str(form, "parent_id")
    parent_id = int(parent_raw) if parent_raw.isdigit() else None
    path = _files_path(project_id, parent_id)
    try:
        folder = await create_folder(
            session,
            user,
            project_id,
            _form_str(form, "name"),
            parent_id,
            _form_roles(form),
        )
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(_files_path(project_id, folder.id), message="Папка создана")


@router.post("/projects/{project_id}/folders/{folder_id}/roles")
async def project_folder_roles(
    project_id: int,
    folder_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    path = _files_path(project_id, folder_id)
    try:
        await update_folder_roles(session, user, project_id, folder_id, _form_roles(form))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Доступ к папке обновлён")


@router.post("/projects/{project_id}/folders/{folder_id}/delete")
async def project_folder_delete(
    project_id: int,
    folder_id: int,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    parent_raw = _form_str(form, "parent_id")
    parent_id = int(parent_raw) if parent_raw.isdigit() else None
    try:
        await delete_folder(session, user, project_id, folder_id, settings.project_files_dir)
    except ProjectError as exc:
        return _redirect(_files_path(project_id, folder_id), error=str(exc))
    return _redirect(_files_path(project_id, parent_id), message="Папка удалена")


@router.post("/projects/{project_id}/files/upload")
async def project_file_upload(
    project_id: int,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    folder_raw = _form_str(form, "folder_id")
    folder_id = int(folder_raw) if folder_raw.isdigit() else None
    path = _files_path(project_id, folder_id)
    upload = form.get("upload")
    if not isinstance(upload, UploadFile):
        return _redirect(path, error="Файл не выбран")
    try:
        await store_file(
            session,
            user,
            project_id,
            folder_id,
            upload,
            settings.project_files_dir,
            _form_roles(form),
        )
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Файл загружен")


@router.post("/projects/{project_id}/files/{file_id}/roles")
async def project_file_roles(
    project_id: int,
    file_id: int,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    folder_raw = _form_str(form, "folder_id")
    folder_id = int(folder_raw) if folder_raw.isdigit() else None
    path = _files_path(project_id, folder_id)
    try:
        await update_file_roles(session, user, project_id, file_id, _form_roles(form))
    except ProjectError as exc:
        return _redirect(path, error=str(exc))
    return _redirect(path, message="Доступ к файлу обновлён")


@router.post("/projects/{project_id}/files/{file_id}/delete")
async def project_file_delete(
    project_id: int,
    file_id: int,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> RedirectResponse:
    form = await request.form()
    folder_raw = _form_str(form, "folder_id")
    folder_id = int(folder_raw) if folder_raw.isdigit() else None
    try:
        await delete_stored_file(
            session, user, project_id, file_id, settings.project_files_dir
        )
    except ProjectError as exc:
        return _redirect(_files_path(project_id, folder_id), error=str(exc))
    return _redirect(_files_path(project_id, folder_id), message="Файл удалён")


@router.get("/projects/{project_id}/files/{file_id}")
async def project_file_download(
    project_id: int,
    file_id: int,
    session: DbSession,
    settings: SettingsDep,
    user: CurrentUser,
) -> Response:
    try:
        item, payload = await read_stored_file(
            session, user, project_id, file_id, settings.project_files_dir
        )
    except ProjectError as exc:
        raise _not_found(exc) from exc
    filename = quote(item.original_name)
    return Response(
        payload,
        media_type=item.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
