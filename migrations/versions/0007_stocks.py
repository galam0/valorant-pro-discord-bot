"""가상 주식 테이블 (종목·보유·가격 기록·경기 반영 기록)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = lambda name: sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)  # noqa: E731
    op.create_table(
        "stocks",
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        ts("updated_at"),
        sa.PrimaryKeyConstraint("symbol", name="pk_stocks"),
    )
    op.create_table(
        "stock_holdings",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("shares", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cost", sa.BigInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("guild_id", "user_id", "symbol", name="pk_stock_holdings"),
    )
    op.create_table(
        "stock_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(20), server_default="tick", nullable=False),
        ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_stock_history"),
    )
    op.create_index("ix_stock_history_symbol_time", "stock_history", ["symbol", "created_at"])
    op.create_table(
        "stock_events",
        sa.Column("match_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        ts("created_at"),
        sa.PrimaryKeyConstraint("match_id", "symbol", name="pk_stock_events"),
    )


def downgrade() -> None:
    op.drop_table("stock_events")
    op.drop_index("ix_stock_history_symbol_time", table_name="stock_history")
    op.drop_table("stock_history")
    op.drop_table("stock_holdings")
    op.drop_table("stocks")
