"""Content scheduling, templates, important kind.

Revision ID: 20260805_0010
Revises: 20260805_0009
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0010"
down_revision: str | None = "20260805_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_MEMES = [
    "Белый дым снова посетил паяльную станцию. Омниссия фиксирует расход предохранителей.",
    "Если сборка завелась с первого раза — проверьте, не сон ли это.",
    "В лаборатории тихо. Слишком тихо. Кто-то снова читает даташит вместо сна.",
    "Прошивка прошла успешно. Пользователь — пока нет.",
    "Калибровка завершена. Мораль инженера — в процессе калибровки.",
]

SEED_TEASERS = [
    "Посмотри, что {name} сделал сегодня! {link}",
    "Свежая хроника от {name} (@{username}): {link}",
    "В Буднях лабы новый отчёт — автор {name}. {link}",
    "Мастерская не спит: {name} выложил прогресс. {link}",
]


def upgrade() -> None:
    op.add_column("content_items", sa.Column("published_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("content_items", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "content_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    templates = sa.table(
        "content_templates",
        sa.column("kind", sa.String),
        sa.column("body", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        templates,
        [{"kind": "meme", "body": body, "is_active": True} for body in SEED_MEMES]
        + [{"kind": "flood_teaser", "body": body, "is_active": True} for body in SEED_TEASERS],
    )


def downgrade() -> None:
    op.drop_table("content_templates")
    op.drop_column("content_items", "scheduled_at")
    op.drop_column("content_items", "published_channel_id")
