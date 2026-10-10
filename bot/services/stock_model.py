"""가상 주식(팀 주가) 규칙 — DB·디스코드 없이 돌아가는 순수 계산.

주가는 서버와 상관없이 하나(전 서버 공통)이고, 보유 주식·VP는 서버별이다.
- 매시 정각에 무작위로 오르내린다.
- 무작위 변동 + 기준가(base) 쪽으로 천천히 돌아오는 힘(평균 회귀) → 한쪽으로 끝없이 가지 않는다.
- 수수료: 사고팔 때 각각 1% (올림, 최소 1 VP).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class StockDef:
    symbol: str      # 종목 코드 (팀 태그)
    name: str        # 표시 이름
    vlr_id: int      # VLR 팀 ID — 경기 결과를 이 팀에 연결
    base: int        # 시작가이자 평균 회귀의 기준가 (VP)


# 인기 6개 팀 (코드 한 줄로 바꿀 수 있다)
STOCKS: tuple[StockDef, ...] = (
    StockDef("GEN", "젠지 (Gen.G)", 17, 300),
    StockDef("T1", "티원 (T1)", 14, 260),
    StockDef("PRX", "페이퍼 렉스 (Paper Rex)", 624, 220),
    StockDef("VL", "바렐 (VARREL)", 11229, 200),
    StockDef("KRX", "키움 DRX (KIWOOM DRX)", 8185, 160),
    StockDef("NS", "농심 레드포스 (Nongshim)", 11060, 140),
)
BY_SYMBOL = {s.symbol: s for s in STOCKS}

FEE_PCT = 1
MIN_QTY, MAX_QTY = 1, 500
FLOOR_RATIO, CEIL_RATIO = 0.25, 4.0     # 주가는 기준가의 25% ~ 400% 안에서만 움직인다
NOISE_SIGMA = 0.025                      # 한 번(1시간)에 움직이는 폭: 보통 ±2.5% 안팎
REVERT = 0.02                            # 한 번에 기준가 쪽으로 돌아오는 힘


def clamp_price(price: float, base: int) -> int:
    return int(round(min(max(price, base * FLOOR_RATIO), base * CEIL_RATIO)))


def apply_move(price: int, base: int, pct: float) -> int:
    new = clamp_price(price * (1 + pct), base)
    if new == price and pct != 0:        # 반올림으로 안 움직이면 최소 1 VP
        new = clamp_price(price + (1 if pct > 0 else -1), base)
    return new


def noise_step(price: int, base: int, rng: random.Random | None = None) -> int:
    """가격 변동 한 번. 기준가보다 높으면 살짝 내리는 쪽, 낮으면 올리는 쪽으로 기운다."""
    r = rng or random
    pull = REVERT * math.log(base / price)
    return apply_move(price, base, r.gauss(0, NOISE_SIGMA) + pull)


def fee(amount: int) -> int:
    """수수료 (올림, 최소 1)."""
    return max(1, -(-amount * FEE_PCT // 100))


def buy_total(price: int, qty: int) -> tuple[int, int]:
    """(주식 값, 수수료)."""
    cost = price * qty
    return cost, fee(cost)


def sell_proceeds(price: int, qty: int) -> tuple[int, int]:
    """(받는 돈, 수수료)."""
    gross = price * qty
    f = fee(gross)
    return gross - f, f


def pct_change(now: int, before: int | None) -> float | None:
    if not before:
        return None
    return (now - before) / before * 100


@dataclass
class Quote:
    symbol: str
    name: str
    price: int
    change_pct: float | None     # 24시간 전 대비
    spark: list[int]
    logo_url: str | None = None


@dataclass
class Trade:
    symbol: str
    qty: int
    price: int
    amount: int       # 주식 값(수수료 제외)
    fee: int
    balance: int
    profit: int | None = None     # 매도 시: 실현 손익 (받은 돈 − 매수 원가)


@dataclass
class Position:
    symbol: str
    name: str
    shares: int
    avg_cost: float
    price: int

    @property
    def value(self) -> int:
        return self.shares * self.price

    @property
    def pnl(self) -> int:
        return int(self.value - self.avg_cost * self.shares)

    @property
    def pnl_pct(self) -> float:
        base = self.avg_cost * self.shares
        return (self.value - base) / base * 100 if base else 0.0


KST = timezone(timedelta(hours=9))


def next_tick_at(now: datetime | None = None) -> datetime:
    """다음 주가 변동 시각 (매시 정각, 한국 시간)."""
    now = (now or datetime.now(KST)).astimezone(KST)
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def rank_investors(holdings: list[tuple[int, str, int, int]], prices: dict[str, int]) -> list[tuple[int, int, int, float]]:
    """(유저, 종목, 주수, 총 매수원가) 목록 → [(유저, 평가액, 평가손익, 수익률%)] 를 평가손익이 큰 순으로.

    아는 종목만 계산한다. 평가액은 수수료 전 금액이고 수익률은 매수원가 기준이다.
    """
    agg: dict[int, list[int]] = {}
    for uid, sym, shares, cost in holdings:
        if sym not in BY_SYMBOL or shares <= 0:
            continue
        a = agg.setdefault(uid, [0, 0])
        a[0] += shares * prices.get(sym, BY_SYMBOL[sym].base)
        a[1] += cost
    out = [(uid, v, v - c, ((v - c) / c * 100) if c > 0 else 0.0) for uid, (v, c) in agg.items()]
    return sorted(out, key=lambda r: (-r[2], r[0]))


SURGE_PCT = 6.0      # 한 번에 이만큼(%) 이상 오르내리면 알림 채널에 알린다


def find_surges(before: dict[str, int], after: dict[str, int], threshold: float = SURGE_PCT) -> list[tuple[str, int, int, float]]:
    """[(종목, 이전가, 새 가격, 등락률%)] — 등락 폭이 큰 순. 아는 종목만, 이전 가격이 없으면 건너뛴다."""
    out = []
    for sym, new in after.items():
        old = before.get(sym)
        if sym not in BY_SYMBOL or not old:
            continue
        pct = (new - old) / old * 100
        if abs(pct) >= threshold:
            out.append((sym, old, new, pct))
    return sorted(out, key=lambda r: -abs(r[3]))


def parse_trade_ref(ref: str | None) -> tuple[str, int, int] | None:
    """장부(ledger)의 ref 'GENx10@1020' → ('GEN', 10, 1020). 형식이 다르면 None."""
    import re

    m = re.fullmatch(r"([A-Z0-9]+)x(\d+)@(\d+)", ref or "")
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else None
