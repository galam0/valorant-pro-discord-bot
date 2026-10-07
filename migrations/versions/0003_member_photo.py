"""로스터 사진: team_members.photo_url

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("team_members", sa.Column("photo_url", sa.Text()))


def downgrade() -> None:
    op.drop_column("team_members", "photo_url")
