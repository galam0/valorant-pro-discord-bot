"""발로란트 개인 상점 연동 상태 테이블 (인증 정보는 저장하지 않음)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valorant_shop_links",
        sa.Column("discord_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("status", sa.String(32), server_default="not_linked", nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(250), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("discord_user_id", name=op.f("pk_valorant_shop_links")),
    )


def downgrade() -> None:
    op.drop_table("valorant_shop_links")
