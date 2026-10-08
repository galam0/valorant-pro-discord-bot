"""가상 주식 DB 함수. 호출하는 쪽의 세션(트랜잭션) 안에서 실행되고 commit 은 호출한 쪽이 한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import economy
from bot.database.models import Match, Stock, StockEvent, StockHistory, StockHolding, Team


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


async def claim_event(session: AsyncSession, match_id: int, symbol: str) -> bool:
    """경기 결과를 이 종목에 반영하는 권리를 얻는다 (이미 반영했으면 False)."""
    row = (await session.execute(
        pg_insert(StockEvent).values(match_id=match_id, symbol=symbol)
        .on_conflict_do_nothing().returning(StockEvent.match_id)
    )).first()
    return row is not None


async def recent_completed_matches(session: AsyncSession, names: list[str], since: datetime) -> list[tuple]:
    """최근 끝난 경기 중 해당 팀(이름)이 포함된 것: (match.id, team1 이름, team2 이름, score1, score2).

    팀이 DB의 teams 에 없어도 경기에는 팀 이름이 저장돼 있어서 이름으로 찾는다.
    """
    rows = await session.execute(
        select(Match.id, Match.team1_name, Match.team2_name, Match.team1_score, Match.team2_score)
        .where(Match.status == "completed", Match.scheduled_at >= since,
               Match.team1_score.is_not(None), Match.team2_score.is_not(None),
               (func.lower(Match.team1_name).in_(names)) | (func.lower(Match.team2_name).in_(names)))
        .order_by(Match.scheduled_at.asc())
    )
    return [tuple(r) for r in rows.all()]


async def team_logos(session: AsyncSession, vlr_ids: list[int]) -> dict[int, str]:
    """DB에 저장된 팀 로고 URL (VLR 팀 ID → URL)."""
    rows = await session.execute(select(Team.vlr_id, Team.logo_url).where(Team.vlr_id.in_(vlr_ids), Team.logo_url.is_not(None)))
    return {int(v): u for v, u in rows.all()}
