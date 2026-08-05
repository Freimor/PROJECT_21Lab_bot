"""Rename top role magister→lord (Лорд remains bootstrap admin).

Revision ID: 20260805_0006
Revises: 20260805_0005
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0006"
down_revision: str | None = "20260805_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET staff_role = 'lord' WHERE staff_role = 'magister'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE users SET staff_role = 'magister' WHERE staff_role = 'lord'"))
