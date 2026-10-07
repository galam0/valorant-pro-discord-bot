"""팀 랭킹 (VLR.gg /rankings). DB를 쓰지 않고 메모리에 캐시한다 (Neon 사용량 절약)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from bot.scrapers.vlr import RankingEntry, vlr

log = logging.getLogger("valobot.service.ranking")

CACHE_TTL = 3600  # 랭킹은 하루 한 번쯤 바뀌므로 1시간 캐시

# (VLR 주소 코드, 한국어 이름)
REGIONS: list[tuple[str, str]] = [
    ("world", "세계"),
    ("korea", "한국"),
    ("asia-pacific", "아시아·태평양"),
    ("japan", "일본"),
    ("china", "중국"),
    ("europe", "유럽"),
    ("north-america", "북미"),
    ("brazil", "브라질"),
    ("la-s", "남미(LA-S)"),
    ("la-n", "중미(LA-N)"),
    ("oceania", "오세아니아"),
    ("mena", "중동·북아프리카"),
    ("gc", "여성 대회(GC)"),
]
REGION_NAME = dict(REGIONS)


@dataclass
class RankingResult:
    region: str
    entries: list[RankingEntry]
    fetched_at: float
    stale: bool = False  # 새로 못 가져와서 이전 결과를 보여주는 경우


_cache: dict[str, RankingResult] = {}
_locks: dict[str, asyncio.Lock] = {}


async def get_ranking(region: str) -> RankingResult:
    cached = _cache.get(region)
    if cached and time.time() - cached.fetched_at < CACHE_TTL:
        return cached
    async with _locks.setdefault(region, asyncio.Lock()):
        cached = _cache.get(region)
        if cached and time.time() - cached.fetched_at < CACHE_TTL:
            return cached
        try:
            entries = await vlr.fetch_rankings(region)
        except Exception:
            if cached:
                log.warning("랭킹 갱신 실패, 이전 결과 사용: %s", region, exc_info=True)
                cached.stale = True
                return cached
            raise
        result = RankingResult(region, entries, time.time())
        _cache[region] = result
        return result
