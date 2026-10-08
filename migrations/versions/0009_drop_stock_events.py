"""경기 결과 반영을 없애면서 stock_events 테이블 삭제

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("stock_events")


def downgrade() -> None:
    op.create_table(
        "stock_events",
        sa.Column("match_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("match_id", "symbol", name="pk_stock_events"),
    )
