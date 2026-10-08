"""서버별 설정 테이블 (/채널설정)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("game_channel_id", sa.BigInteger()),
        sa.Column("notice_channel_id", sa.BigInteger()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("guild_id", name="pk_guild_settings"),
    )


def downgrade() -> None:
    op.drop_table("guild_settings")
