"""VP 지갑·예측 DB 함수.

모든 함수는 호출하는 쪽의 세션(트랜잭션) 안에서 실행된다. commit 은 호출한 쪽이 한다.
→ '잔액 차감 + 예측 저장' 처럼 여러 작업이 한 트랜잭션으로 묶여 중간에 실패하면 모두 취소된다.

잔액은 항상 `UPDATE ... WHERE balance + :delta >= 0` 한 문장으로 바꾼다.
(먼저 읽고 나중에 쓰는 방식은 동시에 두 번 누를 때 잔액이 마이너스가 될 수 있다)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.services.odds_model import CANCEL_FEE_PCT, cancel_fee  # noqa: F401  (재노출)
from bot.database.models import GuildSetting, Match, Prediction, Profile, Purchase, Wallet, WalletLedger

STARTING_VP = 500      # 서버에서 처음 지갑을 만들 때 받는 VP
CHECKIN_VP = 100       # 하루 출석 보상


class InsufficientFunds(Exception):
    """잔액 부족."""


async def ensure_wallet(session: AsyncSession, guild_id: int, user_id: int) -> None:
    """지갑이 없으면 만들고 시작 VP를 준다 (동시에 여러 번 불러도 한 번만 지급)."""
    result = await session.execute(
        pg_insert(Wallet)
        .values(guild_id=guild_id, user_id=user_id, balance=STARTING_VP)
        .on_conflict_do_nothing(index_elements=[Wallet.guild_id, Wallet.user_id])
        .returning(Wallet.guild_id)
    )
    if result.first() is not None:   # 이번에 새로 만들어졌을 때만 원장에 기록
        session.add(WalletLedger(guild_id=guild_id, user_id=user_id, delta=STARTING_VP,
                                 balance_after=STARTING_VP, reason="welcome"))


async def get_balance(session: AsyncSession, guild_id: int, user_id: int) -> int:
    await ensure_wallet(session, guild_id, user_id)
    return (await session.execute(
        select(Wallet.balance).where(Wallet.guild_id == guild_id, Wallet.user_id == user_id)
    )).scalar_one()


async def apply_delta(session: AsyncSession, guild_id: int, user_id: int, delta: int,
                      reason: str, ref: str | None = None) -> int:
    """잔액을 delta 만큼 바꾸고 원장에 기록한다. 마이너스가 되면 InsufficientFunds. 새 잔액을 돌려준다."""
    await ensure_wallet(session, guild_id, user_id)
    row = (await session.execute(
        update(Wallet)
        .where(Wallet.guild_id == guild_id, Wallet.user_id == user_id, Wallet.balance + delta >= 0)
        .values(balance=Wallet.balance + delta)
        .returning(Wallet.balance)
    )).first()
    if row is None:
        raise InsufficientFunds()
    new_balance = int(row[0])
    session.add(WalletLedger(guild_id=guild_id, user_id=user_id, delta=delta,
                             balance_after=new_balance, reason=reason, ref=ref))
    return new_balance


async def checkin(session: AsyncSession, guild_id: int, user_id: int, today: date) -> tuple[bool, int]:
    """출석. (이번에 지급했는지, 현재 잔액). 같은 날 두 번 눌러도 한 번만 지급된다."""
    await ensure_wallet(session, guild_id, user_id)
    claimed = (await session.execute(
        update(Wallet)
        .where(Wallet.guild_id == guild_id, Wallet.user_id == user_id,
               (Wallet.last_checkin_date.is_(None)) | (Wallet.last_checkin_date < today))
        .values(last_checkin_date=today)
        .returning(Wallet.guild_id)
    )).first()
    if claimed is None:
        return False, await get_balance(session, guild_id, user_id)
    return True, await apply_delta(session, guild_id, user_id, CHECKIN_VP, "checkin")


async def leaderboard(session: AsyncSession, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
    rows = await session.execute(
        select(Wallet.user_id, Wallet.balance).where(Wallet.guild_id == guild_id)
        .order_by(Wallet.balance.desc()).limit(limit)
    )
    return [(int(u), int(b)) for u, b in rows]


async def guild_totals(session: AsyncSession) -> list[tuple[int, int, int, int]]:
    """(서버 ID, 지갑 수, 잔액 합계, 최고 잔액) — 봇 제작자용 전체 현황."""
    rows = await session.execute(
        select(Wallet.guild_id, func.count(), func.coalesce(func.sum(Wallet.balance), 0), func.max(Wallet.balance))
        .group_by(Wallet.guild_id).order_by(func.sum(Wallet.balance).desc())
    )
    return [(int(g), int(c), int(s), int(m)) for g, c, s, m in rows]


# ---------------------------------------------------------------------------
# 예측
# ---------------------------------------------------------------------------


async def create_prediction(session: AsyncSession, *, guild_id: int, user_id: int, match_id: int, kind: str,
                            pick: str, pick_label: str, stake: int, odds: float) -> Prediction:
    """VP를 차감하고 예측을 저장한다 (같은 종류는 경기당 1개 — 중복이면 IntegrityError)."""
    pred = Prediction(guild_id=guild_id, user_id=user_id, match_id=match_id, kind=kind, pick=pick,
                      pick_label=pick_label, stake=stake, odds=odds, status="open")
    session.add(pred)
    await session.flush()   # id 확보 + 중복 예측이면 여기서 실패 → 아직 VP는 차감 전
    await apply_delta(session, guild_id, user_id, -stake, "bet", ref=f"prediction:{pred.id}")
    return pred


async def get_user_predictions(session: AsyncSession, guild_id: int, user_id: int, match_id: int) -> list[Prediction]:
    rows = await session.execute(
        select(Prediction).where(Prediction.guild_id == guild_id, Prediction.user_id == user_id,
                                 Prediction.match_id == match_id, Prediction.status != "cancelled")
        .order_by(Prediction.id)
    )
    return list(rows.scalars())


async def get_prediction(session: AsyncSession, prediction_id: int) -> Prediction | None:
    return await session.get(Prediction, prediction_id)


async def cancel_prediction(session: AsyncSession, prediction_id: int, user_id: int) -> tuple[Prediction, int] | None:
    """열린(open) 예측만 취소한다. 수수료 10%를 뗀 나머지를 환불하고 (예측, 수수료)를 돌려준다.

    이미 취소·정산됐거나 남의 예측이면 None. (경기 취소·연기로 인한 자동 환불은 수수료 없이 전액)
    """
    row = (await session.execute(
        update(Prediction)
        .where(Prediction.id == prediction_id, Prediction.user_id == user_id, Prediction.status == "open")
        .values(status="cancelled", settled_at=datetime.now(timezone.utc))
        .returning(Prediction.id)
    )).first()
    if row is None:
        return None
    pred = await session.get(Prediction, prediction_id)
    await session.refresh(pred)
    fee = cancel_fee(pred.stake)
    await apply_delta(session, pred.guild_id, pred.user_id, pred.stake - fee, "refund", ref=f"prediction:{pred.id}")
    return pred, fee


async def open_predictions_for_match(session: AsyncSession, match_id: int) -> list[Prediction]:
    rows = await session.execute(
        select(Prediction).where(Prediction.match_id == match_id, Prediction.status == "open")
    )
    return list(rows.scalars())


async def settle_prediction(session: AsyncSession, pred: Prediction, outcome: str) -> bool:
    """open 예측 하나를 정산한다. outcome: won / lost / void(전액 환불). 이미 정산됐으면 False.

    `status = 'open'` 조건으로 한 번만 처리되게 해서, 정산이 두 번 돌아도 VP가 두 번 지급되지 않는다.
    """
    payout = {"won": int(pred.stake * pred.odds), "void": pred.stake}.get(outcome, 0)
    row = (await session.execute(
        update(Prediction)
        .where(Prediction.id == pred.id, Prediction.status == "open")
        .values(status=outcome, payout=payout, settled_at=datetime.now(timezone.utc))
        .returning(Prediction.id)
    )).first()
    if row is None:
        return False
    if payout > 0:
        await apply_delta(session, pred.guild_id, pred.user_id, payout,
                          "payout" if outcome == "won" else "refund", ref=f"prediction:{pred.id}")
    return True


async def my_predictions(session: AsyncSession, guild_id: int, user_id: int, limit: int = 15) -> list[Prediction]:
    rows = await session.execute(
        select(Prediction).where(Prediction.guild_id == guild_id, Prediction.user_id == user_id,
                                 Prediction.status != "cancelled")
        .options(selectinload(Prediction.match).selectinload(Match.team1), selectinload(Prediction.match).selectinload(Match.team2))
        .order_by(Prediction.id.desc()).limit(limit)
    )
    return list(rows.scalars())


# ---------------------------------------------------------------------------
# 프로필·상점
# ---------------------------------------------------------------------------


class AlreadyOwned(Exception):
    pass


async def get_profile(session: AsyncSession, guild_id: int, user_id: int) -> Profile | None:
    return await session.get(Profile, (guild_id, user_id))


async def upsert_profile(session: AsyncSession, guild_id: int, user_id: int, **fields) -> None:
    """프로필 설정 일부를 바꾼다 (없으면 만든다)."""
    stmt = pg_insert(Profile).values(guild_id=guild_id, user_id=user_id, **fields)
    stmt = stmt.on_conflict_do_update(index_elements=[Profile.guild_id, Profile.user_id],
                                      set_={**fields, "updated_at": func.now()})
    await session.execute(stmt)


async def owned_items(session: AsyncSession, guild_id: int, user_id: int) -> set[str]:
    rows = await session.execute(select(Purchase.item_id).where(Purchase.guild_id == guild_id, Purchase.user_id == user_id))
    return {r for (r,) in rows}


async def buy_item(session: AsyncSession, guild_id: int, user_id: int, item_id: str, price: int) -> int:
    """아이템 구매. 이미 있으면 AlreadyOwned, 잔액이 모자라면 InsufficientFunds. 새 잔액.

    (서버, 유저, 아이템) 기본키 덕분에 같은 아이템을 동시에 두 번 눌러도 한 번만 구매된다.
    """
    row = (await session.execute(
        pg_insert(Purchase).values(guild_id=guild_id, user_id=user_id, item_id=item_id, price=price)
        .on_conflict_do_nothing().returning(Purchase.item_id)
    )).first()
    if row is None:
        raise AlreadyOwned()
    return await apply_delta(session, guild_id, user_id, -price, "shop", ref=item_id)


async def prediction_record(session: AsyncSession, guild_id: int, user_id: int) -> tuple[int, int]:
    """(적중 수, 정산된 예측 수) — 환불·취소는 제외."""
    won = (await session.execute(select(func.count()).select_from(Prediction).where(
        Prediction.guild_id == guild_id, Prediction.user_id == user_id, Prediction.status == "won"))).scalar_one()
    lost = (await session.execute(select(func.count()).select_from(Prediction).where(
        Prediction.guild_id == guild_id, Prediction.user_id == user_id, Prediction.status == "lost"))).scalar_one()
    return int(won), int(won) + int(lost)


async def matches_with_predictions(session: AsyncSession, guild_id: int, limit: int = 25) -> list[tuple[Match, int]]:
    """이 서버에 (취소 안 된) 예측이 있는 경기와 예측 수 — 최근 경기부터."""
    rows = await session.execute(
        select(Match, func.count(Prediction.id))
        .join(Prediction, Prediction.match_id == Match.id)
        .where(Prediction.guild_id == guild_id, Prediction.status != "cancelled")
        .group_by(Match.id)
        .order_by(func.coalesce(Match.scheduled_at, Match.created_at).desc())
        .limit(limit)
    )
    return [(m, int(n)) for m, n in rows.all()]


async def match_predictions(session: AsyncSession, guild_id: int, match_id: int) -> list[Prediction]:
    rows = await session.execute(
        select(Prediction).where(Prediction.guild_id == guild_id, Prediction.match_id == match_id,
                                 Prediction.status != "cancelled")
        .order_by(Prediction.stake.desc(), Prediction.id)
    )
    return list(rows.scalars())


# ---------------------------------------------------------------------------
# 서버 설정 (/채널설정)
# ---------------------------------------------------------------------------


async def get_guild_setting(session: AsyncSession, guild_id: int) -> GuildSetting | None:
    return await session.get(GuildSetting, guild_id)


async def set_guild_channel(session: AsyncSession, guild_id: int, field: str, channel_id: int | None) -> None:
    """field: game_channel_id / notice_channel_id. channel_id=None 이면 해제."""
    if field not in ("game_channel_id", "notice_channel_id"):
        raise ValueError(field)
    stmt = pg_insert(GuildSetting).values(guild_id=guild_id, **{field: channel_id})
    stmt = stmt.on_conflict_do_update(index_elements=[GuildSetting.guild_id],
                                      set_={field: channel_id, "updated_at": func.now()})
    await session.execute(stmt)
