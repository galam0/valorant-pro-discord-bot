"""미니게임·퀴즈의 VP 처리 (DB). 모든 변화는 지갑 원장에 남는다."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from bot.database import economy
from bot.database.database import db
from bot.database.models import WalletLedger
from bot.services import games, quiz_bank
from bot.services.economy_service import KST


class GameError(Exception):
    """사용자에게 그대로 보여줄 메시지."""


def check_bet(stake: int) -> None:
    if not games.MIN_BET <= stake <= games.MAX_BET:
        raise GameError(f"{games.MIN_BET:,}~{games.MAX_BET:,} VP 사이로 걸어주세요.")


async def take_bet(guild_id: int, user_id: int, stake: int, reason: str) -> int:
    """베팅액 차감 (블랙잭 시작용). 새 잔액."""
    check_bet(stake)
    try:
        async with db.session() as s:
            bal = await economy.apply_delta(s, guild_id, user_id, -stake, reason)
            await s.commit()
    except economy.InsufficientFunds:
        raise GameError("VP가 부족해요. `/출석`으로 100 VP를 받을 수 있어요.") from None
    return bal


async def pay(guild_id: int, user_id: int, amount: int, reason: str) -> int:
    """당첨금 지급. 새 잔액."""
    async with db.session() as s:
        bal = await economy.apply_delta(s, guild_id, user_id, amount, reason) if amount > 0 else await economy.get_balance(s, guild_id, user_id)
        await s.commit()
    return bal


async def instant(guild_id: int, user_id: int, stake: int, payout: int, reason: str) -> int:
    """한 번에 끝나는 게임: 베팅 차감 + 당첨금 지급을 한 트랜잭션으로. 새 잔액."""
    check_bet(stake)
    try:
        async with db.session() as s:
            bal = await economy.apply_delta(s, guild_id, user_id, -stake, reason)
            if payout > 0:
                bal = await economy.apply_delta(s, guild_id, user_id, payout, reason + "_win")
            await s.commit()
    except economy.InsufficientFunds:
        raise GameError("VP가 부족해요. `/출석`으로 100 VP를 받을 수 있어요.") from None
    return bal


# ---- 퀴즈 -------------------------------------------------------------------


def _week_start_utc() -> datetime:
    return quiz_bank.week_start(datetime.now(KST))


async def quiz_remaining(guild_id: int, user_id: int) -> int:
    async with db.session() as s:
        used = (await s.execute(
            select(func.count()).select_from(WalletLedger).where(
                WalletLedger.guild_id == guild_id, WalletLedger.user_id == user_id,
                WalletLedger.reason == "quiz_try", WalletLedger.created_at >= _week_start_utc())
        )).scalar_one()
    return max(0, quiz_bank.WEEKLY_LIMIT - int(used))


async def quiz_start(guild_id: int, user_id: int) -> int:
    """도전 1회를 소모한다 (문제를 본 순간 차감 → 모르는 척 닫고 다시 하는 것을 막는다). 남은 횟수."""
    async with db.session() as s:
        await economy.ensure_wallet(s, guild_id, user_id)
        used = (await s.execute(
            select(func.count()).select_from(WalletLedger).where(
                WalletLedger.guild_id == guild_id, WalletLedger.user_id == user_id,
                WalletLedger.reason == "quiz_try", WalletLedger.created_at >= _week_start_utc())
        )).scalar_one()
        if used >= quiz_bank.WEEKLY_LIMIT:
            raise GameError(f"이번 주 퀴즈 {quiz_bank.WEEKLY_LIMIT}회를 모두 사용했어요. 월요일에 초기화돼요.")
        await economy.apply_delta(s, guild_id, user_id, 0, "quiz_try")
        await s.commit()
    return quiz_bank.WEEKLY_LIMIT - int(used) - 1
