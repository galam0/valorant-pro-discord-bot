"""프로필 꾸미기·상점 구매 테이블

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = lambda name: sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)  # noqa: E731
    op.create_table(
        "profiles",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("theme", sa.String(30), server_default="theme_default", nullable=False),
        sa.Column("frame", sa.String(30), server_default="frame_none", nullable=False),
        sa.Column("title", sa.String(30), server_default="title_none", nullable=False),
        sa.Column("fav_team", sa.String(120)),
        sa.Column("fav_agent", sa.String(40)),
        ts("updated_at"),
        sa.PrimaryKeyConstraint("guild_id", "user_id", name="pk_profiles"),
    )
    op.create_table(
        "purchases",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("item_id", sa.String(30), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        ts("created_at"),
        sa.PrimaryKeyConstraint("guild_id", "user_id", "item_id", name="pk_purchases"),
    )


def downgrade() -> None:
    op.drop_table("purchases")
    op.drop_table("profiles")
