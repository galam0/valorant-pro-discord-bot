"""대회 검색 + 대진표 (VLR.gg). DB를 쓰지 않고 메모리에 잠깐 캐시한다 (Neon 사용량 절약)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.scrapers.vlr import EventBracket, EventSearchResult, vlr

log = logging.getLogger("valobot.service.event")

SEARCH_TTL = 3600   # 대회 검색 결과 1시간
BRACKET_TTL = 300   # 대진표 5분 (진행 중 대회는 점수가 자주 바뀜)

# 한국어 대회 이름 → VLR 검색어 (긴 것부터 치환)
KO_EVENT_TERMS: list[tuple[str, str]] = [
    ("챔피언스", "champions"), ("마스터스", "masters"), ("퍼시픽", "pacific"), ("아메리카스", "americas"),
    ("에메아", "emea"), ("차이나", "china"), ("스테이지", "stage"), ("킥오프", "kickoff"), ("런던", "london"),
    ("도쿄", "tokyo"), ("서울", "seoul"), ("상하이", "shanghai"), ("마드리드", "madrid"), ("토론토", "toronto"),
    ("리프팅", "lifting"), ("레드불", "red bull"), ("챌린저스", "challengers"), ("게임체인저스", "game changers"),
    ("발로란트", "valorant"),
]


class EventNotFound(Exception):
    pass


@dataclass
class EventResult:
    bracket: EventBracket
    candidates: list[EventSearchResult]  # 같은 검색어로 찾은 다른 대회 (선택 메뉴용)
    stale: bool = False


def to_query(text: str) -> str:
    q = text.strip()
    for ko, en in KO_EVENT_TERMS:
        q = q.replace(ko, f" {en} ")
    return re.sub(r"\s+", " ", q).strip()


def _prize(e: EventSearchResult) -> int:
    m = re.search(r"\$([\d,]+)", e.desc or "")
    return int(m.group(1).replace(",", "")) if m else 0


def _rank(e: EventSearchResult) -> tuple[int, int, float, int]:
    """정렬 키: 최근 14개월 안의 대회 먼저 → 상금이 큰 순 → 최근 시작 순.
    (예: '챔피언스' → 작은 대회보다 Valorant Champions 2026, 2년 전 대회보다 올해 대회)"""
    now = datetime.now(timezone.utc)
    recent = e.start is not None and (now - e.start).days < 430
    ts = e.start.timestamp() if e.start else 0.0
    return (0 if recent else 1, -_prize(e), -ts, -e.vlr_id)


_search_cache: dict[str, tuple[float, list[EventSearchResult]]] = {}
_bracket_cache: dict[int, tuple[float, EventBracket]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def search(query: str) -> list[EventSearchResult]:
    q = to_query(query)
    if not q:
        return []
    hit = _search_cache.get(q.lower())
    if hit and time.time() - hit[0] < SEARCH_TTL:
        return hit[1]
    results = sorted(await vlr.search_events(q), key=_rank)
    # 검색어가 길어서 결과가 없으면 단어를 줄여 한 번 더 (예: 'champions 2026 group' → 'champions 2026')
    words = q.split()
    while not results and len(words) > 1:
        words = words[:-1]
        results = sorted(await vlr.search_events(" ".join(words)), key=_rank)
    _search_cache[q.lower()] = (time.time(), results)
    return results


async def get_bracket(event_id: int) -> tuple[EventBracket, bool]:
    """(대진표, 이전 결과 여부)"""
    hit = _bracket_cache.get(event_id)
    if hit and time.time() - hit[0] < BRACKET_TTL:
        return hit[1], False
    async with _locks.setdefault(str(event_id), asyncio.Lock()):
        hit = _bracket_cache.get(event_id)
        if hit and time.time() - hit[0] < BRACKET_TTL:
            return hit[1], False
        try:
            bracket = await vlr.fetch_event_bracket(event_id)
        except Exception:
            if hit:
                log.warning("대진표 갱신 실패, 이전 결과 사용: %s", event_id, exc_info=True)
                return hit[1], True
            raise
        _bracket_cache[event_id] = (time.time(), bracket)
        return bracket, False


async def find_bracket(query: str) -> EventResult:
    results = await search(query)
    if not results:
        raise EventNotFound(query)
    bracket, stale = await get_bracket(results[0].vlr_id)
    return EventResult(bracket, results[:10], stale)
