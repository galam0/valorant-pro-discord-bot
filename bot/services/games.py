"""VP 미니게임의 순수 규칙 (DB·Discord 없이 테스트 가능). 모든 게임은 하우스 엣지 약 2.5~5%."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import product

MIN_BET = 10
MAX_BET = 2000

# ---- 동전 ------------------------------------------------------------------
COIN_MULT = 1.95


def coin_flip(rng: random.Random | None = None) -> str:
    return (rng or random).choice(["앞", "뒤"])


# ---- 주사위 ----------------------------------------------------------------
DICE_PARITY_MULT = 1.95   # 홀/짝
DICE_EXACT_MULT = 5.7     # 숫자 맞히기 (1/6)


def dice_payout(pick: str, roll: int, stake: int) -> int:
    """pick: '홀' '짝' '1'~'6'. 이기면 받는 총액(원금 포함), 지면 0."""
    if pick == "홀":
        return int(stake * DICE_PARITY_MULT) if roll % 2 == 1 else 0
    if pick == "짝":
        return int(stake * DICE_PARITY_MULT) if roll % 2 == 0 else 0
    return int(stake * DICE_EXACT_MULT) if pick == str(roll) else 0


# ---- 슬롯 ------------------------------------------------------------------
SLOT_SYMBOLS = [("🍒", 40, 5.0), ("🍋", 30, 10.0), ("🔔", 18, 25.0), ("⭐", 8, 60.0), ("💎", 4, 150.0)]
SLOT_PAIR_MULT = 0.3      # 같은 그림 2개: 일부 환급


def slot_spin(rng: random.Random | None = None) -> list[str]:
    r = rng or random
    names = [s[0] for s in SLOT_SYMBOLS]
    weights = [s[1] for s in SLOT_SYMBOLS]
    return r.choices(names, weights=weights, k=3)


def slot_multiplier(reels: list[str]) -> float:
    if reels[0] == reels[1] == reels[2]:
        return next(m for n, _, m in SLOT_SYMBOLS if n == reels[0])
    if len(set(reels)) == 2:
        return SLOT_PAIR_MULT
    return 0.0


def slot_rtp() -> float:
    """이론상 환급률 (전체 경우의 수를 직접 계산)."""
    total = sum(w for _, w, _ in SLOT_SYMBOLS)
    rtp = 0.0
    for combo in product(SLOT_SYMBOLS, repeat=3):
        p = 1.0
        for _, w, _ in combo:
            p *= w / total
        rtp += p * slot_multiplier([c[0] for c in combo])
    return rtp


# ---- 블랙잭 ----------------------------------------------------------------
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]


def new_deck(rng: random.Random | None = None) -> list[str]:
    deck = [r + s for r in RANKS for s in SUITS]
    (rng or random).shuffle(deck)
    return deck


def hand_value(cards: list[str]) -> int:
    total, aces = 0, 0
    for c in cards:
        rank = c[:-1]
        if rank == "A":
            aces += 1
            total += 11
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


@dataclass
class Blackjack:
    stake: int
    deck: list[str] = field(default_factory=new_deck)
    player: list[str] = field(default_factory=list)
    dealer: list[str] = field(default_factory=list)
    doubled: bool = False
    done: bool = False

    def __post_init__(self) -> None:
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        if is_blackjack(self.player) or is_blackjack(self.dealer):
            self.done = True

    @property
    def total_stake(self) -> int:
        return self.stake * (2 if self.doubled else 1)

    def hit(self) -> None:
        self.player.append(self.deck.pop())
        if hand_value(self.player) >= 21:
            self.stand()

    def double(self) -> None:
        """한 장만 더 받고 종료. 호출 전에 추가 베팅(stake)을 차감해야 한다."""
        self.doubled = True
        self.player.append(self.deck.pop())
        self.stand()

    def stand(self) -> None:
        if hand_value(self.player) <= 21:
            while hand_value(self.dealer) < 17:      # 딜러는 17 이상에서 멈춘다 (소프트 17 포함)
                self.dealer.append(self.deck.pop())
        self.done = True

    def result(self) -> tuple[str, int]:
        """(결과, 돌려받는 총액). 결과: blackjack / win / push / lose / bust"""
        p, d = hand_value(self.player), hand_value(self.dealer)
        bet = self.total_stake
        if is_blackjack(self.player):
            return ("push", bet) if is_blackjack(self.dealer) else ("blackjack", int(bet * 2.5))
        if is_blackjack(self.dealer):
            return "lose", 0
        if p > 21:
            return "bust", 0
        if d > 21 or p > d:
            return "win", bet * 2
        if p == d:
            return "push", bet
        return "lose", 0
