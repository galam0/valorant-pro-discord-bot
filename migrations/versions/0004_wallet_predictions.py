"""VP 지갑·원장·예측 테이블

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = lambda name: sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)  # noqa: E731
    op.create_table(
        "wallets",
        sa.Column("guild_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_checkin_date", sa.Date()),
        ts("created_at"),
        ts("updated_at"),
        sa.PrimaryKeyConstraint("guild_id", "user_id", name="pk_wallets"),
    )
    op.create_table(
        "wallet_ledger",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("ref", sa.String(60)),
        ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_wallet_ledger"),
    )
    op.create_index("ix_wallet_ledger_user", "wallet_ledger", ["guild_id", "user_id", "created_at"])
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("pick", sa.String(120), nullable=False),
        sa.Column("pick_label", sa.String(160), nullable=False),
        sa.Column("stake", sa.BigInteger(), nullable=False),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(12), server_default="open", nullable=False),
        sa.Column("payout", sa.BigInteger(), server_default="0", nullable=False),
        ts("created_at"),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name="fk_predictions_match_id_matches", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_predictions"),
        sa.UniqueConstraint("guild_id", "user_id", "match_id", "kind", name="uq_predictions_one_per_kind"),
    )
    op.create_index("ix_predictions_match_status", "predictions", ["match_id", "status"])
    op.create_index("ix_predictions_user", "predictions", ["guild_id", "user_id", "status"])


def downgrade() -> None:
    op.drop_table("predictions")
    op.drop_table("wallet_ledger")
    op.drop_table("wallets")
