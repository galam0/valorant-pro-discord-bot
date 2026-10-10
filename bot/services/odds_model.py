"""예측 게임 배율 계산과 정산 규칙 (DB·Discord 없이 계산만 하는 순수 함수 모음).

배율 정책
- 승패: VLR 경기 페이지에 나온 배당을 그대로 쓴다 (여러 곳이면 평균). 없으면 기본 1.90 / 1.90.
- 스코어: VLR 배당으로 구한 팀 승리 확률 → '맵 한 개를 이길 확률'을 역산 → 각 스코어(2:0, 2:1 …)의 확률
  → 배율 = (1 - 수수료 5%) / 확률.  (직접 만든 계산식이라 VLR 값은 아님)
- MVP: 팀 승리 확률에 따라 그 팀 선수의 MVP 확률을 정하고(이긴 팀에서 MVP가 나올 가능성이 더 큼),
  선수 한 명의 확률 = 팀 확률 / 5.  배율 = (1 - 수수료) / 확률.
- 상한/하한을 둬서 극단적인 배율이 나오지 않게 한다.

MVP 정의: 경기 전체(시리즈) 합산 스탯에서 레이팅 1위 (같으면 ACS가 높은 선수).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb

HOUSE_EDGE = 0.05          # 스코어·MVP 배율에 적용하는 수수료
DEFAULT_ODDS = 1.90        # VLR 배당이 없을 때 승패 기본 배율
MIN_MULT, MAX_MULT = 1.05, 30.0
MVP_MIN_MULT, MVP_MAX_MULT = 3.0, 30.0
MIN_STAKE, MAX_STAKE = 10, 2000
LOCK_MINUTES = 10          # 경기 시작 이 분 전에 예측 마감


def wins_needed(best_of: str | None) -> int | None:
    """'BO3' → 2, 'BO5' → 3, 'BO1' → 1. 모르면 None."""
    if not best_of:
        return None
    digits = "".join(ch for ch in best_of if ch.isdigit())
    return (int(digits) + 1) // 2 if digits else None


def series_win_prob(q: float, n: int) -> float:
    """맵 한 개를 이길 확률 q 일 때, n승 선취 시리즈를 이길 확률."""
    return sum(comb(n - 1 + j, j) * (q ** n) * ((1 - q) ** j) for j in range(n))


def map_win_prob(p_series: float, n: int) -> float:
    """시리즈 승리 확률 p 에서 맵 승리 확률 q 를 이분법으로 역산 (q가 클수록 p도 커진다)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if series_win_prob(mid, n) < p_series:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _mult(prob: float, lo: float = MIN_MULT, hi: float = MAX_MULT) -> float:
    if prob <= 0:
        return hi
    return round(min(max((1 - HOUSE_EDGE) / prob, lo), hi), 2)


@dataclass
class Odds:
    """한 경기의 배율표. team1_p: 팀1 승리 확률."""

    team1_p: float
    winner: tuple[float, float]               # (팀1 승, 팀2 승) 배율
    from_vlr: bool                            # VLR 배당을 썼는지 (False면 기본 배율)


def build_odds(vlr: object | None) -> Odds:
    """vlr: parse_match_odds 결과(MatchOdds) 또는 None."""
    if vlr is None:
        return Odds(0.5, (DEFAULT_ODDS, DEFAULT_ODDS), False)
    return Odds(float(vlr.p1), (float(vlr.team1_odds), float(vlr.team2_odds)), True)  # type: ignore[attr-defined]


def score_options(p1: float, best_of: str | None) -> list[tuple[str, float]]:
    """가능한 스코어와 배율 [('2-0', 3.1), ('2-1', 3.8), ('1-2', ...), ('0-2', ...)] (팀1-팀2 순서)."""
    n = wins_needed(best_of)
    if not n or n < 2:       # 단판은 맵 점수 예측 불가
        return []
    q = map_win_prob(p1, n)
    out: list[tuple[str, float]] = []
    for j in range(n):       # 팀1이 n:j 로 이김
        out.append((f"{n}-{j}", _mult(comb(n - 1 + j, j) * q ** n * (1 - q) ** j)))
    for j in range(n - 1, -1, -1):   # 팀2가 n 으로 이김 → 팀1은 j
        out.append((f"{j}-{n}", _mult(comb(n - 1 + j, j) * (1 - q) ** n * q ** j)))
    return out


def mvp_multiplier(p_team: float) -> float:
    """선수가 속한 팀의 승리 확률 p_team → 그 선수의 MVP 배율."""
    p_side = min(max(0.5 + 0.7 * (p_team - 0.5), 0.15), 0.85)
    return _mult(p_side / 5, MVP_MIN_MULT, MVP_MAX_MULT)


def payout(stake: int, odds: float) -> int:
    """적중 시 돌려받는 총액 (건 VP 포함, 소수점은 버림)."""
    return int(stake * odds)


# ---------------------------------------------------------------------------
# 마감 규칙
# ---------------------------------------------------------------------------


def betting_state(now, scheduled_at, status: str) -> str:
    """'open' | 'locked'(시작 10분 전~시작) | 'started'(시작했거나 끝남) | 'unknown'(시간 미정).

    now, scheduled_at 은 시간대가 있는 datetime.
    """
    from datetime import timedelta

    if status in ("live", "completed"):
        return "started"
    if scheduled_at is None:
        return "unknown"
    if now >= scheduled_at:
        return "started"
    if now >= scheduled_at - timedelta(minutes=LOCK_MINUTES):
        return "locked"
    return "open"


# ---------------------------------------------------------------------------
# 정산 규칙
# ---------------------------------------------------------------------------


def norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _g(obj: object, key: str):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def mvp_of(stats_all: list[list[object]] | None) -> str | None:
    """시리즈 합산 스탯에서 MVP 이름. 스탯이 없거나 레이팅을 못 읽으면 None."""
    if not stats_all:
        return None
    best: tuple[float, float, str] | None = None
    for team in stats_all:
        for p in team:
            try:
                rating = float(_g(p, "rating") or "")
            except ValueError:
                continue
            try:
                acs = float(_g(p, "acs") or 0)
            except ValueError:
                acs = 0.0
            cand = (rating, acs, _g(p, "name") or "")
            if best is None or cand[:2] > best[:2]:
                best = cand
    return best[2] if best else None


def settle_outcome(kind: str, pick: str, *, score1: int | None, score2: int | None, mvp: str | None) -> str:
    """'won' / 'lost' / 'void'. 결과를 알 수 없으면 void(전액 환불)."""
    if score1 is None or score2 is None or score1 == score2:
        return "void"
    if kind == "winner":
        return "won" if (pick == "1") == (score1 > score2) else "lost"
    if kind == "score":
        return "won" if pick == f"{score1}-{score2}" else "lost"
    if kind == "mvp":
        if not mvp:
            return "void"
        return "won" if norm(pick) == norm(mvp) else "lost"
    return "void"


CANCEL_FEE_PCT = 10    # 예측을 직접 취소할 때 떼는 수수료(%)


def cancel_fee(stake: int) -> int:
    """직접 취소 수수료 (걸었던 VP의 10%, 소수점 버림). 경기 취소·연기로 인한 자동 환불에는 없다."""
    return stake * CANCEL_FEE_PCT // 100


def pick_fans(rows: list[tuple[int, str | None]], team1: str, team2: str, limit: int = 20) -> list[int]:
    """(유저, 응원 팀) 목록에서 이 경기의 두 팀 중 하나를 응원하는 유저 ID (앞에서 limit명, 중복 제거)."""
    teams = {norm(team1), norm(team2)} - {""}
    out: list[int] = []
    for uid, fav in rows:
        if fav and norm(fav) in teams and uid not in out:
            out.append(uid)
            if len(out) >= limit:
                break
    return out
