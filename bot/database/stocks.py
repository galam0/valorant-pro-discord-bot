"""가상 주식 DB 함수. 호출하는 쪽의 세션(트랜잭션) 안에서 실행되고 commit 은 호출한 쪽이 한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import economy
from bot.database.models import Stock, StockHistory, StockHolding, Team, WalletLedger


class NotEnoughShares(Exception):
    """보유 수량 부족."""


async def ensure_stocks(session: AsyncSession, defs) -> None:
    """종목이 없으면 시작가로 만든다 (이미 있으면 그대로)."""
    for d in defs:
        row = (await session.execute(
            pg_insert(Stock).values(symbol=d.symbol, price=d.base)
            .on_conflict_do_nothing(index_elements=[Stock.symbol]).returning(Stock.symbol)
        )).first()
        if row is not None:
            session.add(StockHistory(symbol=d.symbol, price=d.base, reason="init"))


async def get_prices(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(Stock.symbol, Stock.price))
    return {sym: int(p) for sym, p in rows.all()}


async def set_price(session: AsyncSession, symbol: str, price: int, reason: str) -> None:
    await session.execute(update(Stock).where(Stock.symbol == symbol).values(price=price, updated_at=func.now()))
    session.add(StockHistory(symbol=symbol, price=price, reason=reason))


async def price_before(session: AsyncSession, symbol: str, hours: int = 24) -> int | None:
    """hours 시간 전의 주가 (그때 기록이 없으면 가장 오래된 기록)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    row = (await session.execute(
        select(StockHistory.price).where(StockHistory.symbol == symbol, StockHistory.created_at <= cutoff)
        .order_by(StockHistory.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        row = (await session.execute(
            select(StockHistory.price).where(StockHistory.symbol == symbol)
            .order_by(StockHistory.created_at.asc()).limit(1)
        )).scalar_one_or_none()
    return int(row) if row is not None else None


async def recent_prices(session: AsyncSession, symbol: str, limit: int = 40) -> list[int]:
    rows = await session.execute(
        select(StockHistory.price).where(StockHistory.symbol == symbol)
        .order_by(StockHistory.created_at.desc(), StockHistory.id.desc()).limit(limit)
    )
    return [int(p) for (p,) in rows.all()][::-1]


async def buy(session: AsyncSession, guild_id: int, user_id: int, symbol: str, qty: int, price: int,
              cost: int, fee: int) -> int:
    """VP를 내고 주식을 산다. 잔액이 모자라면 economy.InsufficientFunds. 새 잔액을 돌려준다."""
    bal = await economy.apply_delta(session, guild_id, user_id, -(cost + fee), "stock_buy", ref=f"{symbol}x{qty}@{price}")
    stmt = pg_insert(StockHolding).values(guild_id=guild_id, user_id=user_id, symbol=symbol, shares=qty, cost=cost)
    stmt = stmt.on_conflict_do_update(
        index_elements=[StockHolding.guild_id, StockHolding.user_id, StockHolding.symbol],
        set_={"shares": StockHolding.shares + qty, "cost": StockHolding.cost + cost})
    await session.execute(stmt)
    return bal


async def sell(session: AsyncSession, guild_id: int, user_id: int, symbol: str, qty: int, price: int,
               proceeds: int) -> tuple[int, int]:
    """주식을 팔고 VP를 받는다. (새 잔액, 판 만큼의 매수 원가). 수량이 모자라면 NotEnoughShares.

    `shares >= qty` 조건을 건 UPDATE 한 문장이라 동시에 두 번 눌러도 보유량보다 많이 팔 수 없다.
    """
    before = (await session.execute(
        select(StockHolding.shares, StockHolding.cost).where(
            StockHolding.guild_id == guild_id, StockHolding.user_id == user_id, StockHolding.symbol == symbol)
        .with_for_update()
    )).first()
    if before is None or before[0] < qty:
        raise NotEnoughShares()
    shares, cost = int(before[0]), int(before[1])
    cost_out = cost * qty // shares
    row = (await session.execute(
        update(StockHolding)
        .where(StockHolding.guild_id == guild_id, StockHolding.user_id == user_id, StockHolding.symbol == symbol,
               StockHolding.shares >= qty)
        .values(shares=StockHolding.shares - qty, cost=StockHolding.cost - cost_out)
        .returning(StockHolding.shares)
    )).first()
    if row is None:
        raise NotEnoughShares()
    bal = await economy.apply_delta(session, guild_id, user_id, proceeds, "stock_sell", ref=f"{symbol}x{qty}@{price}")
    return bal, cost_out


async def holdings(session: AsyncSession, guild_id: int, user_id: int) -> list[StockHolding]:
    rows = await session.execute(
        select(StockHolding).where(StockHolding.guild_id == guild_id, StockHolding.user_id == user_id,
                                   StockHolding.shares > 0).order_by(StockHolding.symbol)
    )
    return list(rows.scalars())


async def team_logos(session: AsyncSession, vlr_ids: list[int]) -> dict[int, str]:
    """DB에 저장된 팀 로고 URL (VLR 팀 ID → URL)."""
    rows = await session.execute(select(Team.vlr_id, Team.logo_url).where(Team.vlr_id.in_(vlr_ids), Team.logo_url.is_not(None)))
    return {int(v): u for v, u in rows.all()}


async def guild_holdings(session: AsyncSession, guild_id: int) -> list[StockHolding]:
    """서버 전체의 보유 주식 (랭킹용)."""
    rows = await session.execute(select(StockHolding).where(StockHolding.guild_id == guild_id, StockHolding.shares > 0))
    return list(rows.scalars())


async def trade_history(session: AsyncSession, guild_id: int, user_id: int, limit: int = 15) -> list[tuple[str, int, str | None, datetime]]:
    """최근 주식 거래 (reason, VP 변화, ref, 시각) — 새것부터. 지갑 장부를 그대로 읽으므로 별도 테이블이 없다."""
    rows = await session.execute(
        select(WalletLedger.reason, WalletLedger.delta, WalletLedger.ref, WalletLedger.created_at)
        .where(WalletLedger.guild_id == guild_id, WalletLedger.user_id == user_id,
               WalletLedger.reason.in_(("stock_buy", "stock_sell")))
        .order_by(WalletLedger.created_at.desc(), WalletLedger.id.desc()).limit(limit))
    return [(r, int(d), ref, at) for r, d, ref, at in rows.all()]
