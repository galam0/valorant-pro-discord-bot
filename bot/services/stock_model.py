"""가상 주식(팀 주가) 규칙 — DB·디스코드 없이 돌아가는 순수 계산.

주가는 서버와 상관없이 하나(전 서버 공통)이고, 보유 주식·VP는 서버별이다.
- 경기 결과: 이긴 팀 +, 진 팀 −. 이변(주가가 낮은 팀이 이김)이거나 스코어 차이가 크면 더 크게 움직인다.
- 시간당 잡음: 작은 무작위 변동 + 기준가(base) 쪽으로 천천히 돌아오는 힘(평균 회귀) → 한쪽으로 끝없이 가지 않는다.
- 수수료: 사고팔 때 각각 1% (올림, 최소 1 VP).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class StockDef:
    symbol: str      # 종목 코드 (팀 태그)
    name: str        # 표시 이름
    vlr_id: int      # VLR 팀 ID — 경기 결과를 이 팀에 연결
    base: int        # 시작가이자 평균 회귀의 기준가 (VP)
    names: tuple[str, ...] = ()   # VLR 경기 목록에 나오는 팀 이름들 (소문자 비교)


# 인기 6개 팀 (코드 한 줄로 바꿀 수 있다)
STOCKS: tuple[StockDef, ...] = (
    StockDef("GEN", "젠지 (Gen.G)", 17, 300, ("gen.g",)),
    StockDef("T1", "티원 (T1)", 14, 260, ("t1",)),
    StockDef("PRX", "페이퍼 렉스 (Paper Rex)", 624, 220, ("paper rex",)),
    StockDef("VL", "바렐 (VARREL)", 11229, 200, ("varrel",)),
    StockDef("KRX", "키움 DRX (KIWOOM DRX)", 8185, 160, ("kiwoom drx", "drx")),
    StockDef("NS", "농심 레드포스 (Nongshim)", 11060, 140, ("nongshim redforce",)),
)
BY_SYMBOL = {s.symbol: s for s in STOCKS}
BY_NAME = {n: s for s in STOCKS for n in s.names}

FEE_PCT = 1
MIN_QTY, MAX_QTY = 1, 500
FLOOR_RATIO, CEIL_RATIO = 0.25, 4.0     # 주가는 기준가의 25% ~ 400% 안에서만 움직인다
WIN_MOVE = 0.04                          # 이긴 팀 기본 상승률
UPSET_BONUS = 0.02                       # 주가가 낮은 팀이 이겼을 때 추가
SWEEP_BONUS = 0.01                       # 스코어 차이가 클 때(2점 이상) 추가
NOISE_SIGMA = 0.008                      # 시간당 잡음 (±0.8%)
REVERT = 0.03                            # 시간당 기준가로 돌아오는 힘


def clamp_price(price: float, base: int) -> int:
    return int(round(min(max(price, base * FLOOR_RATIO), base * CEIL_RATIO)))


def match_move(winner_price: int, loser_price: int, winner_score: int, loser_score: int) -> float:
    """경기 결과로 이긴 팀이 오르는 비율 (진 팀은 같은 비율만큼 내린다). 예: 0.06 = 6%."""
    move = WIN_MOVE
    if winner_price < loser_price:
        move += UPSET_BONUS
    if winner_score - loser_score >= 2:
        move += SWEEP_BONUS
    return move


def apply_move(price: int, base: int, pct: float) -> int:
    new = clamp_price(price * (1 + pct), base)
    if new == price and pct != 0:        # 반올림으로 안 움직이면 최소 1 VP
        new = clamp_price(price + (1 if pct > 0 else -1), base)
    return new


def noise_step(price: int, base: int, rng: random.Random | None = None) -> int:
    """시간당 잡음 한 번. 기준가보다 높으면 살짝 내리는 쪽, 낮으면 올리는 쪽으로 기운다."""
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
