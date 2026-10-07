"""팀 맵 통계: DB에서 팀을 찾고 VLR 팀 통계 페이지를 읽는다. 1시간 메모리 캐시."""

from __future__ import annotations

import time

from bot.database import repository as repo
from bot.database.database import db
from bot.scrapers.vlr import TeamMapStat, vlr

TTL = 3600
PERIODS = {"90": 90, "180": 180, "all": None}
PERIOD_KO = {"90": "최근 90일", "180": "최근 180일", "all": "전체 기간"}
_cache: dict[tuple[int, str], tuple[float, list[TeamMapStat]]] = {}


class TeamNotFound(Exception):
    def __init__(self, query: str, candidates: list | None = None) -> None:
        super().__init__(query)
        self.candidates = candidates or []


async def get_team_maps(query: str, period: str = "180"):
    """(팀, 맵 통계 목록, 오타 보정 여부, 기간을 전체로 넓혔는지)."""
    if period not in PERIODS:
        period = "180"
    async with db.session() as s:
        found = await repo.find_team(s, query)
    team = found.team
    if team is None:
        raise TeamNotFound(query, found.candidates)

    async def load(p: str) -> list[TeamMapStat]:
        key = (team.vlr_id, p)
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
        rows = await vlr.fetch_team_maps(team.vlr_id, PERIODS[p])
        _cache[key] = (time.monotonic(), rows)
        return rows

    rows = await load(period)
    widened = False
    if not rows and period != "all":
        rows, widened = await load("all"), True
    return team, rows, getattr(found, "guessed", False), widened
