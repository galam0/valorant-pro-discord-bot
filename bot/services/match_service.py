"""경기 관련 비즈니스 로직."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from bot.database import repository as repo
from bot.database.database import db
from bot.database.models import Match
from bot.scrapers.vlr import vlr

log = logging.getLogger("valobot.service.match")

# 경기 상세 캐시 유효 시간
DETAIL_TTL = {
    "live": timedelta(seconds=60),       # 진행 중: 1분마다 최신화
    "upcoming": timedelta(minutes=10),
    "completed": None,                   # 종료: 한 번 가져오면 다시 요청하지 않음
}
_detail_locks: dict[int, asyncio.Lock] = {}


@dataclass
class MatchDetailResult:
    match: Match
    stale: bool = False  # 새로 가져오기에 실패해서 예전 데이터를 보여주는 경우


def _detail_is_fresh(match: Match) -> bool:
    if not match.detail or match.detail_scraped_at is None:
        return False
    status = match.detail.get("status", match.status)
    ttl = DETAIL_TTL.get(status, timedelta(minutes=10))
    if ttl is None:
        return True
    return repo.utcnow() - match.detail_scraped_at < ttl


async def get_match_detail(vlr_id: int, *, force: bool = False) -> MatchDetailResult:
    """경기 상세(맵별 점수·선수 스탯).

    DB 캐시를 먼저 보고, 오래됐을 때만 VLR에서 가져와 DB에 저장한 뒤 돌려준다.
    (웹사이트 → 스크래퍼 → DB → 봇 흐름 유지. 같은 경기를 여러 명이 동시에 열어도 요청은 1번)
    """
    lock = _detail_locks.setdefault(vlr_id, asyncio.Lock())
    async with lock:
        async with db.session() as s:
            cached = await repo.get_match_by_vlr_id(s, vlr_id)
        if cached is not None and not force and _detail_is_fresh(cached):
            return MatchDetailResult(cached)

        try:
            full = await vlr.fetch_match_full(vlr_id)
        except Exception as exc:
            if cached is not None and cached.detail:
                log.warning("경기 상세 갱신 실패, 캐시 사용 (match %s): %s", vlr_id, exc)
                return MatchDetailResult(cached, stale=True)
            raise

        async with db.session() as s:
            match = await repo.save_match_full(s, full, url=cached.vlr_url if cached else None)
            await s.commit()
        return MatchDetailResult(match)


async def refresh_matches(include_results: bool = True) -> int:
    """VLR 예정/진행 경기(+최근 결과 1페이지)를 DB에 저장. 저장한 경기 수 반환.

    요청 수: /matches 1 + /matches/results 1 + 시간대 보정용 경기 상세 최대 1 (6시간마다)
    """
    if not db.configured:
        raise RuntimeError("DB가 설정되지 않았습니다.")

    async with db.session() as s:
        run = await repo.start_scrape_run(s, "vlr", "matches")
        await s.commit()
        run_id = run.id

    try:
        items = await vlr.fetch_upcoming_matches()
        if include_results:
            items += await vlr.fetch_results()
        async with db.session() as s:
            count = await repo.upsert_match_list(s, items)
            run = await s.get(repo.ScrapeRun, run_id)
            await repo.finish_scrape_run(s, run, items=count)
            await s.commit()
    except Exception as exc:
        log.warning("경기 갱신 실패: %s", exc)
        async with db.session() as s:
            run = await s.get(repo.ScrapeRun, run_id)
            if run is not None:
                await repo.finish_scrape_run(s, run, error=f"{type(exc).__name__}: {exc}")
                await s.commit()
        raise

    log.info("경기 %d개 저장", count)
    return count
