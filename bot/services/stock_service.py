"""가상 주식 서비스: 시세 조회, 매수·매도, 경기 결과·시간당 변동 반영."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bot.database import economy, stocks
from bot.database.database import db
from bot.services import stock_model as sm
from bot.services.stock_model import Position, Quote, Trade

log = logging.getLogger("valobot.service.stock")

RESULT_WINDOW = timedelta(days=1)    # 이 기간 안에 끝난 경기만 주가에 반영 (오래된 경기가 한꺼번에 반영되는 것 방지)


class StockError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류."""


def _check_symbol(symbol: str) -> sm.StockDef:
    d = sm.BY_SYMBOL.get(symbol.upper())
    if d is None:
        raise StockError("없는 종목이에요. `/주식`에서 종목을 확인하세요.")
    return d


def _check_qty(qty: int) -> None:
    if not sm.MIN_QTY <= qty <= sm.MAX_QTY:
        raise StockError(f"한 번에 {sm.MIN_QTY}~{sm.MAX_QTY}주까지 거래할 수 있어요.")


_logo_cache: dict[int, str | None] = {}    # DB에 없는 팀의 로고 (VLR 팀 페이지에서 한 번만 가져온다)


async def _logo_urls(db_logos: dict[int, str]) -> dict[int, str | None]:
    out: dict[int, str | None] = {}
    for d in sm.STOCKS:
        if d.vlr_id in db_logos:
            out[d.vlr_id] = db_logos[d.vlr_id]
            continue
        if d.vlr_id not in _logo_cache:
            try:
                from bot.scrapers.vlr import vlr
                _logo_cache[d.vlr_id] = (await vlr.fetch_team(d.vlr_id)).logo_url
            except Exception as exc:     # 로고를 못 가져와도 시세판은 보여준다 (코드 배지로 대체)
                log.info("[주식] %s 로고 가져오기 실패: %s: %s", d.symbol, type(exc).__name__, exc)
                continue            # 실패는 캐시하지 않아 다음에 다시 시도
        out[d.vlr_id] = _logo_cache.get(d.vlr_id)
    return out


async def board() -> list[Quote]:
    async with db.session() as s:
        await stocks.ensure_stocks(s, sm.STOCKS)
        await s.commit()
        prices = await stocks.get_prices(s)
        db_logos = await stocks.team_logos(s, [d.vlr_id for d in sm.STOCKS])
        out = []
        for d in sm.STOCKS:
            p = prices.get(d.symbol, d.base)
            out.append(Quote(d.symbol, d.name, p, sm.pct_change(p, await stocks.price_before(s, d.symbol)),
                             await stocks.recent_prices(s, d.symbol)))
    logos = await _logo_urls(db_logos)
    for q, d in zip(out, sm.STOCKS):
        q.logo_url = logos.get(d.vlr_id)
    return out


async def buy(guild_id: int, user_id: int, symbol: str, qty: int) -> Trade:
    d = _check_symbol(symbol)
    _check_qty(qty)
    async with db.session() as s:
        await stocks.ensure_stocks(s, sm.STOCKS)
        price = (await stocks.get_prices(s)).get(d.symbol, d.base)
        cost, fee = sm.buy_total(price, qty)
        try:
            bal = await stocks.buy(s, guild_id, user_id, d.symbol, qty, price, cost, fee)
        except economy.InsufficientFunds:
            raise StockError(f"VP가 부족해요. 필요한 금액은 수수료 포함 {cost + fee:,} VP예요.") from None
        await s.commit()
    return Trade(d.symbol, qty, price, cost, fee, bal)


async def sell(guild_id: int, user_id: int, symbol: str, qty: int) -> Trade:
    d = _check_symbol(symbol)
    _check_qty(qty)
    async with db.session() as s:
        await stocks.ensure_stocks(s, sm.STOCKS)
        price = (await stocks.get_prices(s)).get(d.symbol, d.base)
        proceeds, fee = sm.sell_proceeds(price, qty)
        try:
            bal, cost_out = await stocks.sell(s, guild_id, user_id, d.symbol, qty, price, proceeds)
        except stocks.NotEnoughShares:
            raise StockError("가진 주식보다 많이 팔 수 없어요. `/내주식`에서 보유량을 확인하세요.") from None
        await s.commit()
    return Trade(d.symbol, qty, price, price * qty, fee, bal, profit=proceeds - cost_out)


async def portfolio(guild_id: int, user_id: int) -> tuple[list[Position], int]:
    """(보유 종목들, 현금 VP)."""
    async with db.session() as s:
        await stocks.ensure_stocks(s, sm.STOCKS)
        prices = await stocks.get_prices(s)
        rows = await stocks.holdings(s, guild_id, user_id)
        cash = await economy.get_balance(s, guild_id, user_id)
        await s.commit()
    out = []
    for h in rows:
        d = sm.BY_SYMBOL.get(h.symbol)
        if d is None:
            continue
        out.append(Position(h.symbol, d.name, int(h.shares), h.cost / h.shares, prices.get(h.symbol, d.base)))
    return out, cash


# ---------------------------------------------------------------------------
# 가격 변동 (scheduler 가 부른다 — DB 접근은 필요할 때만)
# ---------------------------------------------------------------------------


async def apply_results() -> int:
    """최근에 끝난 경기를 주가에 반영한다 (경기·종목마다 한 번만). 반영한 종목 수."""
    since = datetime.now(timezone.utc) - RESULT_WINDOW
    applied = 0
    async with db.session() as s:
        await stocks.ensure_stocks(s, sm.STOCKS)
        prices = await stocks.get_prices(s)
        matches = await stocks.recent_completed_matches(s, list(sm.BY_NAME), since)
        for match_id, n1, n2, sc1, sc2 in matches:
            if sc1 == sc2:
                continue
            win_n, lose_n, ws, ls = (n1, n2, sc1, sc2) if sc1 > sc2 else (n2, n1, sc2, sc1)
            w, l = sm.BY_NAME.get(win_n.lower()), sm.BY_NAME.get(lose_n.lower())
            # 상대 팀이 종목이 아니어도, 그 팀의 기준가를 몰라 '이변' 판정은 못 하니 기본 상승률만 쓴다.
            w_price = prices.get(w.symbol) if w else None
            l_price = prices.get(l.symbol) if l else None
            move = sm.match_move(w_price or 0, l_price or 10**9, ws, ls) if w_price else sm.WIN_MOVE
            for d, sign in ((w, 1), (l, -1)):
                if d is None or not await stocks.claim_event(s, match_id, d.symbol):
                    continue
                new = sm.apply_move(prices[d.symbol], d.base, sign * move)
                await stocks.set_price(s, d.symbol, new, "match")
                prices[d.symbol] = new
                applied += 1
        if applied:
            await s.commit()
    if applied:
        log.info("[주식] 경기 결과 반영: %d종목", applied)
    return applied


async def tick() -> None:
    """시간당 잡음 + 기준가로의 평균 회귀."""
    async with db.session() as s:
        await stocks.ensure_stocks(s, sm.STOCKS)
        prices = await stocks.get_prices(s)
        for d in sm.STOCKS:
            await stocks.set_price(s, d.symbol, sm.noise_step(prices.get(d.symbol, d.base), d.base), "tick")
        await s.commit()
