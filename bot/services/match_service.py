"""경기 관련 비즈니스 로직."""

from __future__ import annotations

import logging

from bot.database import repository as repo
from bot.database.database import db
from bot.scrapers.vlr import vlr

log = logging.getLogger("valobot.service.match")


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
