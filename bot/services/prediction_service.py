"""경기 예측 게임: 시장(배율표) 조회, 예측 걸기/취소, 경기 종료 후 정산.

흐름
- 사용자가 /예측 으로 경기를 열면 load_market() 이 VLR 경기 페이지에서 배당·BO를 읽고(5분 캐시)
  DB의 로스터로 MVP 후보를 만든다. → 이때 보여준 배율이 그대로 예측에 고정된다.
- place() 는 마감(시작 10분 전)·잔액·중복을 검사하고 VP 차감 + 예측 저장을 한 트랜잭션으로 한다.
- 정산은 경기가 끝났을 때 scheduler 가 settle_match()/settle_finished() 를 부른다 (DB 접근은 필요할 때만).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from bot.database import economy
from bot.database import repository as repo
from bot.database.database import db
from bot.database.models import Match, Prediction
from bot.services import odds_model as om
from bot.utils.korean import STAFF_ROLES

log = logging.getLogger("valobot.service.prediction")

PAGE_TTL = 300          # VLR 경기 페이지(배당) 캐시 5분
MARKET_MAX_AGE = 900    # 화면에 띄운 배율은 15분까지만 유효 (오래된 화면으로 베팅 방지)
VOID_AFTER = timedelta(days=3)   # 예정 시간이 지나고도 이 기간 안에 끝나지 않으면 취소(전액 환불)
_page_cache: dict[int, tuple[float, object]] = {}
_page_locks: dict[int, asyncio.Lock] = {}


class PredictionError(Exception):
    """사용자에게 그대로 보여줄 수 있는 메시지."""


class BettingClosed(PredictionError):
    def __init__(self, state: str) -> None:
        self.state = state
        text = {
            "started": "이미 경기가 시작되었어요.",
            "locked": "예측이 마감되었어요. (경기 시작 10분 전까지만 가능해요)",
            "unknown": "경기 시간이 아직 정해지지 않아 예측할 수 없어요.",
        }.get(state, "지금은 예측할 수 없어요.")
        super().__init__(text)


@dataclass
class Market:
    match_id: int                  # DB id
    vlr_id: int
    team1: str
    team2: str
    scheduled_at: datetime | None
    status: str
    best_of: str | None
    odds: om.Odds
    roster1: list[str] = field(default_factory=list)
    roster2: list[str] = field(default_factory=list)
    tournament: str | None = None
    fetched_at: float = field(default_factory=time.monotonic)

    @property
    def age(self) -> float:
        return time.monotonic() - self.fetched_at

    def state(self, now: datetime | None = None) -> str:
        return om.betting_state(now or datetime.now(timezone.utc), self.scheduled_at, self.status)

    def score_options(self) -> list[tuple[str, float]]:
        return om.score_options(self.odds.team1_p, self.best_of or "BO3")

    def mvp_mult(self, side: int) -> float:
        p = self.odds.team1_p if side == 1 else 1 - self.odds.team1_p
        return om.mvp_multiplier(p)

    def side_name(self, side: int) -> str:
        return self.team1 if side == 1 else self.team2


async def _vlr_page(vlr_id: int):
    """경기 페이지 파싱 결과 (배당·BO 포함). 5분 캐시, 같은 경기 동시 요청은 1번만."""
    from bot.scrapers.vlr import vlr

    lock = _page_locks.setdefault(vlr_id, asyncio.Lock())
    async with lock:
        hit = _page_cache.get(vlr_id)
        if hit and time.monotonic() - hit[0] < PAGE_TTL:
            return hit[1]
        full = await vlr.fetch_match_full(vlr_id)
        _page_cache[vlr_id] = (time.monotonic(), full)
        return full


async def _roster(session, team_id: int | None) -> list[str]:
    if team_id is None:
        return []
    detail = await repo.get_team_detail(session, team_id, match_limit=0)
    if detail is None:
        return []
    players = [m for m in detail.members if m.role not in STAFF_ROLES and m.role != "inactive"]
    starters = [m.name for m in players if m.role == "player"]
    return starters if len(starters) >= 5 else [m.name for m in players]


def is_tbd(name: str) -> bool:
    return not name or name.strip().upper() == "TBD"


async def load_market(vlr_id: int) -> Market:
    async with db.session() as s:
        match = await repo.get_match_by_vlr_id(s, vlr_id)
        if match is None:
            raise PredictionError("경기 정보를 찾을 수 없어요.")
        if is_tbd(match.team1_name) or is_tbd(match.team2_name):
            raise PredictionError("상대 팀이 아직 정해지지 않은 경기예요.")
        roster1, roster2 = await _roster(s, match.team1_id), await _roster(s, match.team2_id)
        info = dict(match_id=match.id, vlr_id=match.vlr_id, team1=match.team1_name, team2=match.team2_name,
                    scheduled_at=match.scheduled_at, status=match.status, tournament=match.tournament_name,
                    best_of=(match.detail or {}).get("best_of"))

    vlr_odds = None
    try:
        full = await _vlr_page(vlr_id)
        vlr_odds = full.detail.odds
        info["best_of"] = full.best_of or info["best_of"]
        if full.status in ("live", "completed"):
            info["status"] = full.status
    except Exception as exc:     # VLR가 안 되면 기본 배율로 진행 (예측 자체는 막지 않는다)
        log.warning("배당 조회 실패 (match %s): %s", vlr_id, exc)
    return Market(odds=om.build_odds(vlr_odds), roster1=roster1, roster2=roster2, **info)


async def upcoming_markets_list(limit: int = 10) -> list[Match]:
    """예측 가능한 경기 목록: 예정이고 양 팀이 정해졌으며 시작 10분 전 이전."""
    async with db.session() as s:
        rows = await repo.get_upcoming_matches(s, limit=40)
    now = datetime.now(timezone.utc)
    out = [m for m in rows if m.status == "upcoming" and not is_tbd(m.team1_name) and not is_tbd(m.team2_name)
           and m.scheduled_at and m.scheduled_at - timedelta(minutes=om.LOCK_MINUTES) > now]
    return out[:limit]


async def my_for_match(guild_id: int, user_id: int, match_id: int) -> list[Prediction]:
    async with db.session() as s:
        return await economy.get_user_predictions(s, guild_id, user_id, match_id)


async def my_recent(guild_id: int, user_id: int, limit: int = 15) -> list[Prediction]:
    async with db.session() as s:
        return await economy.my_predictions(s, guild_id, user_id, limit)


async def place(*, guild_id: int, user_id: int, market: Market, kind: str, pick: str, pick_label: str,
                odds: float, stake: int) -> tuple[Prediction, int]:
    """예측을 건다. (예측, 남은 잔액). 사용자에게 보여줄 오류는 PredictionError 로 낸다."""
    from sqlalchemy.exc import IntegrityError

    if market.age > MARKET_MAX_AGE:
        raise PredictionError("배율 정보가 오래됐어요. `/예측`으로 다시 열어주세요.")
    if not om.MIN_STAKE <= stake <= om.MAX_STAKE:
        raise PredictionError(f"{om.MIN_STAKE:,}~{om.MAX_STAKE:,} VP 사이로 걸어주세요.")
    try:
        async with db.session() as s:
            match = await s.get(Match, market.match_id)
            state = om.betting_state(datetime.now(timezone.utc), match.scheduled_at, match.status)
            if state != "open":
                raise BettingClosed(state)
            pred = await economy.create_prediction(
                s, guild_id=guild_id, user_id=user_id, match_id=market.match_id, kind=kind,
                pick=pick, pick_label=pick_label, stake=stake, odds=odds)
            balance = await economy.get_balance(s, guild_id, user_id)
            await s.commit()
    except IntegrityError:
        raise PredictionError("이 경기에는 이미 같은 종류의 예측을 했어요. 취소하고 다시 걸 수 있어요.") from None
    except economy.InsufficientFunds:
        raise PredictionError("VP가 부족해요. `/출석`으로 100 VP를 받을 수 있어요.") from None
    return pred, balance


async def cancel(*, user_id: int, prediction_id: int) -> tuple[Prediction, int]:
    """시작 전까지 취소 가능, 전액 환불. (취소된 예측, 잔액)."""
    async with db.session() as s:
        pred = await economy.get_prediction(s, prediction_id)
        if pred is None or pred.user_id != user_id:
            raise PredictionError("예측을 찾을 수 없어요.")
        match = await s.get(Match, pred.match_id)
        if om.betting_state(datetime.now(timezone.utc), match.scheduled_at, match.status) in ("started",):
            raise BettingClosed("started")
        cancelled = await economy.cancel_prediction(s, prediction_id, user_id)
        if cancelled is None:
            raise PredictionError("이미 취소되었거나 정산된 예측이에요.")
        balance = await economy.get_balance(s, cancelled.guild_id, user_id)
        await s.commit()
    return cancelled, balance


# ---------------------------------------------------------------------------
# 정산
# ---------------------------------------------------------------------------


@dataclass
class SettleSummary:
    won: int = 0
    lost: int = 0
    void: int = 0

    @property
    def total(self) -> int:
        return self.won + self.lost + self.void


async def _settle_one_match(s, match: Match) -> SettleSummary:
    summary = SettleSummary()
    preds = await economy.open_predictions_for_match(s, match.id)
    if not preds:
        return summary
    stats = ((match.detail or {}).get("stats") or {}).get("all")
    mvp = om.mvp_of(stats)
    for pred in preds:
        if match.status == "completed":
            outcome = om.settle_outcome(pred.kind, pred.pick, score1=match.team1_score, score2=match.team2_score, mvp=mvp)
        else:
            outcome = "void"
        if await economy.settle_prediction(s, pred, outcome):
            setattr(summary, outcome, getattr(summary, outcome) + 1)
    return summary


async def settle_match(vlr_id: int) -> SettleSummary:
    """경기 하나를 정산 (끝난 경기만). 예측이 없으면 아무것도 쓰지 않는다."""
    async with db.session() as s:
        match = await repo.get_match_by_vlr_id(s, vlr_id)
        if match is None or match.status != "completed":
            return SettleSummary()
        summary = await _settle_one_match(s, match)
        if summary.total:
            await s.commit()
    if summary.total:
        log.info("[예측] 정산 match %s: 적중 %d · 실패 %d · 환불 %d", vlr_id, summary.won, summary.lost, summary.void)
    return summary


async def settle_finished() -> SettleSummary:
    """열린 예측이 있는 끝난 경기를 모두 정산하고, 오래 안 끝난 경기는 취소(환불). 시간당 한 번 정도 부른다."""
    from sqlalchemy import select

    total = SettleSummary()
    now = datetime.now(timezone.utc)
    async with db.session() as s:
        ids = (await s.execute(
            select(Match.id).join(Prediction, Prediction.match_id == Match.id)
            .where(Prediction.status == "open").distinct()
        )).scalars().all()
        for mid in ids:
            match = await s.get(Match, mid)
            stale = (match.status != "completed" and match.scheduled_at is not None
                     and now - match.scheduled_at > VOID_AFTER)
            if match.status != "completed" and not stale:
                continue
            part = await _settle_one_match(s, match if match.status == "completed" else _as_void(match))
            total.won += part.won
            total.lost += part.lost
            total.void += part.void
        if total.total:
            await s.commit()
    if total.total:
        log.info("[예측] 일괄 정산: 적중 %d · 실패 %d · 환불 %d", total.won, total.lost, total.void)
    return total


def _as_void(match: Match):
    """취소/연기 경기: completed 가 아니므로 _settle_one_match 가 전부 void 로 처리한다."""
    return match
