"""팀 관련 비즈니스 로직.

명령어(UI)와 스케줄러, 추후 자연어(AI) 질의가 모두 이 계층을 호출한다.
스크래퍼 → DB 저장, DB 조회를 묶는 역할이며 Discord 객체는 다루지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bot.database import repository as repo
from bot.database.database import db
from bot.scrapers.http import ScrapeError
from bot.scrapers.vlr import ParseError, TeamSearchResult, vlr
from bot.utils.aliases import KO_TEAM_ALIASES

log = logging.getLogger("valobot.service.team")


class TeamNotFound(Exception):
    pass


@dataclass
class TeamRefreshResult:
    team_id: int
    vlr_id: int
    name: str
    roster_count: int
    match_count: int
    note: str | None = None  # 검색어와 정확히 일치하지 않아 고른 경우 안내


def _pick_search_result(query: str, results: list[TeamSearchResult]) -> tuple[TeamSearchResult | None, str | None]:
    """검색 결과에서 팀 고르기. 정확히 일치하는 활동 중인 팀을 우선한다."""
    if not results:
        return None, None
    q = repo.normalize_key(query)
    active = [r for r in results if not r.inactive]
    for pool in (active, results):
        exact = [r for r in pool if repo.normalize_key(r.name) == q]
        if exact:
            return exact[0], None
    best = active[0] if active else results[0]
    return best, f"'{query}'와 정확히 같은 팀이 없어 '{best.name}'을(를) 선택했습니다."


async def _resolve_vlr_id(query: str) -> tuple[int, str | None]:
    """검색어 → VLR 팀 ID. DB에 있는 팀(별칭 포함)이면 검색 없이 바로 사용한다."""
    query = query.strip()
    if query.isdigit():
        return int(query), None

    if db.configured:
        async with db.session() as s:
            lookup = await repo.find_team(s, query)
        if lookup.team is not None:
            return lookup.team.vlr_id, None

    results = await vlr.search_teams(query)
    picked, note = _pick_search_result(query, results)
    if picked is None:
        raise TeamNotFound(query)
    return picked.vlr_id, note


async def refresh_team(query: str) -> TeamRefreshResult:
    """VLR에서 팀 정보를 가져와 DB에 저장한다.

    예외: TeamNotFound, ScrapeError(네트워크), ParseError(사이트 구조 변경)
    """
    if not db.configured:
        raise RuntimeError("DB가 설정되지 않았습니다.")

    async with db.session() as s:
        run = await repo.start_scrape_run(s, "vlr", "team", target=query)
        await s.commit()
        run_id = run.id

    try:
        vlr_id, note = await _resolve_vlr_id(query)
        page = await vlr.fetch_team(vlr_id)
        async with db.session() as s:
            team_id = await repo.upsert_team_page(s, page)
            for alias in KO_TEAM_ALIASES.get(repo.normalize_key(page.name), []):
                await repo.add_team_alias(s, team_id, alias, source="manual")
            run = await s.get(repo.ScrapeRun, run_id)
            await repo.finish_scrape_run(s, run, items=1)
            await s.commit()
    except (TeamNotFound, ScrapeError, ParseError, Exception) as exc:
        log.warning("팀 갱신 실패 (%s): %s", query, exc)
        async with db.session() as s:
            run = await s.get(repo.ScrapeRun, run_id)
            if run is not None:
                await repo.finish_scrape_run(s, run, error=f"{type(exc).__name__}: {exc}")
                await s.commit()
        raise

    log.info("팀 저장: %s (vlr %s) 로스터 %d명, 경기 %d개", page.name, vlr_id, len(page.roster),
             len(page.upcoming) + len(page.recent))
    return TeamRefreshResult(
        team_id=team_id,
        vlr_id=vlr_id,
        name=page.name,
        roster_count=len(page.roster),
        match_count=len(page.upcoming) + len(page.recent),
        note=note,
    )


async def get_team(query: str) -> tuple[repo.TeamDetail | None, list[repo.Team]]:
    """DB에서 팀 조회. (상세, 후보 목록) — 확정 못 하면 상세는 None."""
    async with db.session() as s:
        lookup = await repo.find_team(s, query)
        if lookup.team is None:
            return None, lookup.candidates
        return await repo.get_team_detail(s, lookup.team.id), []
