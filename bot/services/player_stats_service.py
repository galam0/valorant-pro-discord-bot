"""선수 통계 (VLR 요원별 통계). DB에서 선수를 찾고 VLR 선수 페이지를 읽는다. 결과는 1시간 메모리 캐시."""

from __future__ import annotations

import logging
import time

from bot.database import repository as repo
from bot.database.database import db
from bot.scrapers.vlr import PlayerStatsPage, vlr

log = logging.getLogger("valobot.service.player_stats")

TTL = 3600
TIMESPANS = ("30d", "60d", "90d", "all")
_cache: dict[tuple[int, str], tuple[float, PlayerStatsPage]] = {}


class PlayerNotFound(Exception):
    def __init__(self, query: str, candidates: list[repo.Player] | None = None) -> None:
        super().__init__(query)
        self.candidates = candidates or []


class NoVlrProfile(Exception):
    """DB에는 있지만 VLR 선수 번호를 모르는 선수."""

    def __init__(self, nickname: str) -> None:
        super().__init__(nickname)
        self.nickname = nickname


async def _page(vlr_id: int, timespan: str) -> PlayerStatsPage:
    key = (vlr_id, timespan)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    page = await vlr.fetch_player(vlr_id, timespan)
    _cache[key] = (time.monotonic(), page)
    return page


async def get_player_stats(query: str, timespan: str = "90d") -> tuple[PlayerStatsPage, repo.Player, bool, bool]:
    """반환: (통계, DB 선수, 오타 보정 여부, 기간을 전체로 바꿨는지)."""
    if timespan not in TIMESPANS:
        timespan = "90d"
    async with db.session() as s:
        lookup = await repo.find_player(s, query)
    player = lookup.player
    if player is None:
        raise PlayerNotFound(query, lookup.candidates)
    if not player.vlr_id:
        raise NoVlrProfile(player.nickname)
    page = await _page(player.vlr_id, timespan)
    widened = False
    if not page.agents and timespan != "all":
        page = await _page(player.vlr_id, "all")
        widened = True
    return page, player, lookup.guessed, widened
