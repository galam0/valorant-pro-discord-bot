"""팀 랭킹 (VLR.gg /rankings). DB를 쓰지 않고 메모리에 캐시한다 (Neon 사용량 절약)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass

from bot.scrapers.vlr import RankingEntry, vlr
from bot.utils.aliases import MAJOR_TEAMS

log = logging.getLogger("valobot.service.ranking")

CACHE_TTL = 3600  # 랭킹은 하루 한 번쯤 바뀌므로 1시간 캐시

# (VLR 주소 코드, 한국어 이름)
REGIONS: list[tuple[str, str]] = [
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


# 2·3군(아카데미/유스 등) 팀 이름에 들어가는 단어
_ACADEMY_WORDS = {"academy", "youth", "junior", "juniors", "rising", "next", "female", "ladies", "gc", "challengers",
                  "development", "amateur", "prospects", "2", "ii", "b", "women"}


def _tokens(name: str) -> list[str]:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


_MAJOR_TOKENS = [_tokens(q) for q in MAJOR_TEAMS]


def is_first_team(name: str) -> bool:
    """1군(주요 리그 소속) 팀인지: 이름이 MAJOR_TEAMS 중 하나를 단어 단위로 포함하고, 아카데미류 단어가 없어야 한다."""
    toks = _tokens(name)
    if not toks or _ACADEMY_WORDS & set(toks):
        return False
    for q in _MAJOR_TOKENS:
        n = len(q)
        if n and any(toks[i:i + n] == q for i in range(len(toks) - n + 1)):
            return True
    return False


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
