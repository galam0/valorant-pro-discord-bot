"""경기 상세 캐시: matches.detail(JSONB), matches.detail_scraped_at

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("detail", postgresql.JSONB()))
    op.add_column("matches", sa.Column("detail_scraped_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("matches", "detail_scraped_at")
    op.drop_column("matches", "detail")
