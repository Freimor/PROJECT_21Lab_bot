"""Project boards, planner tasks, docs, and private files.

Revision ID: 20260925_0034
Revises: 20260814_0033
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260925_0034"
down_revision: str | None = "20260814_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id"),
            nullable=False,
        ),
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
    op.create_table(
        "project_columns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_project_columns_project_position",
        "project_columns",
        ["project_id", "position"],
    )
    op.create_table(
        "project_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False, server_default="#6b7c93"),
        sa.UniqueConstraint("project_id", "title", name="uq_project_tags_title"),
    )
    op.create_table(
        "project_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_id", sa.Integer(), sa.ForeignKey("project_columns.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("color", sa.String(length=7), nullable=False, server_default="#ff7a25"),
        sa.Column("start_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id"),
            nullable=False,
        ),
        sa.Column("link_kind", sa.String(length=16), nullable=True),
        sa.Column("link_id", sa.Integer(), nullable=True),
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
    op.create_index("ix_project_tasks_column_position", "project_tasks", ["column_id", "position"])
    op.create_index("ix_project_tasks_dates", "project_tasks", ["start_on", "due_on"])
    op.create_table(
        "project_task_assignees",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("project_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), primary_key=True),
    )
    op.create_table(
        "project_task_tags",
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("project_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("project_tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "project_docs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
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
    op.create_table(
        "project_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allowed_roles", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.ForeignKeyConstraint(["parent_id"], ["project_folders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_project_folders_parent", "project_folders", ["project_id", "parent_id"])
    op.create_table(
        "project_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "folder_id",
            sa.Integer(),
            sa.ForeignKey("project_folders.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False, unique=True),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_by",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id"),
            nullable=False,
        ),
        sa.Column("allowed_roles", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_project_files_folder", "project_files", ["project_id", "folder_id"])


def downgrade() -> None:
    op.drop_index("ix_project_files_folder", table_name="project_files")
    op.drop_table("project_files")
    op.drop_index("ix_project_folders_parent", table_name="project_folders")
    op.drop_table("project_folders")
    op.drop_table("project_docs")
    op.drop_table("project_task_tags")
    op.drop_table("project_task_assignees")
    op.drop_index("ix_project_tasks_dates", table_name="project_tasks")
    op.drop_index("ix_project_tasks_column_position", table_name="project_tasks")
    op.drop_table("project_tasks")
    op.drop_table("project_tags")
    op.drop_index("ix_project_columns_project_position", table_name="project_columns")
    op.drop_table("project_columns")
    op.drop_table("projects")
