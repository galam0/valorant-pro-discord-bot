"""VP(가상 재화) 지갑: 잔액·출석·순위·관리자 현황. 서버(guild)별로 따로 관리한다."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.database import economy
from bot.database.database import db

KST = ZoneInfo(os.getenv("DISPLAY_TZ", "Asia/Seoul"))
CURRENCY = "VP"


def today() -> "datetime.date":
    return datetime.now(KST).date()


def fmt(n: int) -> str:
    return f"{n:,} {CURRENCY}"


async def balance(guild_id: int, user_id: int) -> int:
    async with db.session() as s:
        value = await economy.get_balance(s, guild_id, user_id)
        await s.commit()          # 지갑이 새로 만들어졌을 수 있다
    return value


async def checkin(guild_id: int, user_id: int) -> tuple[bool, int]:
    """(이번에 받았는지, 현재 잔액)."""
    async with db.session() as s:
        got, bal = await economy.checkin(s, guild_id, user_id, today())
        await s.commit()
    return got, bal


async def rank_info(guild_id: int, user_id: int) -> tuple[int, int]:
    """(서버 내 순위, 지갑 수). 순위는 잔액이 더 많은 사람 수 + 1."""
    from sqlalchemy import func, select

    from bot.database.models import Wallet

    async with db.session() as s:
        mine = (await s.execute(select(Wallet.balance).where(Wallet.guild_id == guild_id, Wallet.user_id == user_id))).scalar()
        total = (await s.execute(select(func.count()).select_from(Wallet).where(Wallet.guild_id == guild_id))).scalar_one()
        if mine is None:
            return total + 1, total
        higher = (await s.execute(select(func.count()).select_from(Wallet)
                                  .where(Wallet.guild_id == guild_id, Wallet.balance > mine))).scalar_one()
    return int(higher) + 1, int(total)


async def leaderboard(guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
    async with db.session() as s:
        return await economy.leaderboard(s, guild_id, limit)


async def all_guild_totals() -> list[tuple[int, int, int, int]]:
    async with db.session() as s:
        return await economy.guild_totals(s)


async def admin_grant(guild_id: int, user_id: int, amount: int) -> int:
    """관리자 지급/회수 (amount는 음수 가능). 새 잔액."""
    async with db.session() as s:
        bal = await economy.apply_delta(s, guild_id, user_id, amount, "admin")
        await s.commit()
    return bal
