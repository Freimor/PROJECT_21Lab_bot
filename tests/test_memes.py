from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lab21_bot.models import (
    ContentItem,
    ContentKind,
    ContentStatus,
    StaffRole,
    TemplateKind,
    User,
)
from lab21_bot.services.memes import (
    approve_meme_to_collection,
    reject_meme_application,
)
from lab21_bot.services.reactions import sync_post_reaction_total
from lab21_bot.services.templates import list_meme_collection


async def test_approve_meme_increments_counter(session: AsyncSession) -> None:
    author = User(telegram_id=1, full_name="Мемодел", is_approved=True)
    watcher = User(telegram_id=2, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([author, watcher])
    await session.flush()

    item = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.MEME,
        status=ContentStatus.MODERATION,
        source_text="Белый дым снова здесь",
        draft_text="Белый дым снова здесь\n\n— Мемодел",
        media=[{"type": "photo", "file_id": "AgAC-test-photo"}],
    )
    session.add(item)
    await session.flush()

    approved, template = await approve_meme_to_collection(session, watcher, item.id)
    assert approved.status is ContentStatus.APPROVED
    assert template.kind is TemplateKind.MEME
    assert template.author_id == author.telegram_id
    assert author.approved_meme_count == 1
    assert template.title == "Белый дым снова здесь"
    assert template.media == [{"type": "photo", "file_id": "AgAC-test-photo"}]

    collection = await list_meme_collection(session)
    assert len(collection) == 1
    assert collection[0].id == template.id


async def test_reject_meme_application(session: AsyncSession) -> None:
    author = User(telegram_id=3, full_name="Автор", is_approved=True)
    watcher = User(telegram_id=4, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([author, watcher])
    await session.flush()
    item = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.MEME,
        status=ContentStatus.MODERATION,
        source_text="Кринж",
        draft_text="Кринж",
    )
    session.add(item)
    await session.flush()

    rejected = await reject_meme_application(session, watcher, item.id)
    assert rejected.status is ContentStatus.REJECTED
    assert author.approved_meme_count == 0


async def test_meme_reactions_sync_to_collection(session: AsyncSession) -> None:
    author = User(telegram_id=5, full_name="Автор", is_approved=True)
    watcher = User(telegram_id=6, full_name="Смотрящий", staff_role=StaffRole.WATCHER)
    session.add_all([author, watcher])
    await session.flush()
    item = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.MEME,
        status=ContentStatus.MODERATION,
        source_text="Пайка благословлена",
        draft_text="Пайка благословлена",
    )
    session.add(item)
    await session.flush()
    _, template = await approve_meme_to_collection(session, watcher, item.id)

    published = ContentItem(
        author_id=author.telegram_id,
        kind=ContentKind.MEME,
        status=ContentStatus.PUBLISHED,
        source_text=template.body,
        draft_text=template.body,
        published_channel_id=-1001,
        published_message_id=99,
        template_id=template.id,
        reaction_count=0,
    )
    session.add(published)
    await session.flush()

    await sync_post_reaction_total(
        session, chat_id=-1001, message_id=99, total_reactions=4
    )
    await session.refresh(template)
    assert template.reaction_count == 4
    # +1 за одобрение мема, +4 за реакции
    assert author.respect == 5


def test_read_uploaded_meme_file(tmp_path) -> None:
    from lab21_bot.services.uploads import UploadError, read_uploaded_file

    folder = tmp_path / "memes"
    folder.mkdir()
    (folder / "shot.jpg").write_bytes(b"jpeg-bytes")
    content, content_type = read_uploaded_file(tmp_path, "memes/shot.jpg")
    assert content == b"jpeg-bytes"
    assert content_type == "image/jpeg"
    with pytest.raises(UploadError):
        read_uploaded_file(tmp_path, "../secret.jpg")


async def test_meme_application_media_serves_saved_file(tmp_path) -> None:
    from lab21_bot.admin.routes.publications import _proxy_media_file

    folder = tmp_path / "memes"
    folder.mkdir()
    (folder / "shot.jpg").write_bytes(b"jpeg-bytes")
    settings = SimpleNamespace(upload_dir=str(tmp_path))
    response = await _proxy_media_file(
        settings,
        [{"type": "photo", "path": "memes/shot.jpg"}],
        0,
    )
    assert response.status_code == 200
    assert response.body == b"jpeg-bytes"
    assert response.media_type == "image/jpeg"
