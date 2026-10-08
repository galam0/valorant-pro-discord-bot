"""종목 교체: 피나틱(FNC)·센티넬즈(SEN) 상장폐지 → 키움 DRX(KRX)·바렐(VL)

혹시 보유자가 있으면 현재 주가로 VP를 돌려주고(수수료 없음) 기록을 지운다.
새 종목은 봇이 처음 쓸 때 시작가로 자동 생성된다.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "('FNC', 'SEN')"


def upgrade() -> None:
    op.execute(f"""
        WITH refund AS (
            SELECT h.guild_id, h.user_id, SUM(h.shares * s.price)::bigint AS amt
            FROM stock_holdings h JOIN stocks s ON s.symbol = h.symbol
            WHERE h.symbol IN {OLD} AND h.shares > 0
            GROUP BY h.guild_id, h.user_id
        ), upd AS (
            UPDATE wallets w SET balance = w.balance + r.amt
            FROM refund r WHERE w.guild_id = r.guild_id AND w.user_id = r.user_id
            RETURNING w.guild_id, w.user_id, r.amt, w.balance
        )
        INSERT INTO wallet_ledger (guild_id, user_id, delta, balance_after, reason, ref)
        SELECT guild_id, user_id, amt, balance, 'stock_delist', 'delist' FROM upd
    """)
    for table in ("stock_holdings", "stock_history", "stock_events", "stocks"):
        op.execute(f"DELETE FROM {table} WHERE symbol IN {OLD}")


def downgrade() -> None:
    pass
