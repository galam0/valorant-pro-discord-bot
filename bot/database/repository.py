"""DB 접근 함수 모음.

명령어(UI)나 스크래퍼는 SQL을 직접 쓰지 않고 이 모듈의 함수만 호출한다.
쓰기는 외부 고유 ID(vlr_id 등)를 기준으로 upsert 해서 같은 데이터가 중복 저장되지 않게 한다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.database.models import (
    Crosshair,
    Equipment,
    Match,
    Player,
    PlayerSettings,
    ScrapeRun,
    Team,
    TeamAlias,
    TeamMember,
    Tournament,
)
from bot.scrapers.vlr import EventRef, MatchFull, MatchListItem, TeamMatchItem, TeamPage

# /관리 상태 에 보여줄 테이블과 한국어 이름
COUNTED_TABLES: tuple[tuple[str, type], ...] = (
    ("팀", Team),
    ("팀 별칭", TeamAlias),
    ("선수", Player),
    ("로스터", TeamMember),
    ("대회", Tournament),
    ("경기", Match),
    ("선수 설정", PlayerSettings),
    ("장비", Equipment),
    ("크로스헤어", Crosshair),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_key(text_: str) -> str:
    """검색 키 정규화: 소문자, 영문·숫자·한글만 남김. 'GEN.G' → 'geng', '젠 지' → '젠지'."""
    return re.sub(r"[^0-9a-z가-힣]", "", text_.lower())


def slugify(text_: str) -> str:
    return re.sub(r"[^0-9a-z]+", "-", text_.lower()).strip("-")


# ---------------------------------------------------------------------------
# 상태 / 통계
# ---------------------------------------------------------------------------


async def get_table_counts(session: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, model in COUNTED_TABLES:
        result = await session.execute(select(func.count()).select_from(model))
        counts[label] = int(result.scalar_one())
    return counts


async def get_schema_revision(session: AsyncSession) -> str | None:
    """현재 적용된 Alembic 리비전. 테이블이 없으면 None."""
    # 테이블이 없을 때 SELECT가 실패하면 트랜잭션이 깨지므로 존재 여부를 먼저 확인
    exists = await session.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
    if not exists.scalar_one():
        return None
    result = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 수집 기록
# ---------------------------------------------------------------------------


async def start_scrape_run(session: AsyncSession, source: str, job: str, target: str | None = None) -> ScrapeRun:
    run = ScrapeRun(source=source, job=job, target=target, status="running")
    session.add(run)
    await session.flush()
    return run


async def finish_scrape_run(
    session: AsyncSession, run: ScrapeRun, *, items: int = 0, error: str | None = None
) -> None:
    run.status = "failed" if error else "success"
    run.items = items
    run.error = error[:2000] if error else None
    run.finished_at = utcnow()
    await session.flush()


async def get_last_scrape_runs(session: AsyncSession, limit: int = 10) -> list[ScrapeRun]:
    result = await session.execute(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit))
    return list(result.scalars())


# ---------------------------------------------------------------------------
# 팀 저장 (VLR 팀 페이지 → teams, players, team_members, team_aliases, matches)
# ---------------------------------------------------------------------------


async def add_team_alias(session: AsyncSession, team_id: int, alias: str, source: str = "manual") -> bool:
    """별칭 추가. 이미 다른 팀이 쓰는 별칭이면 추가하지 않고 False."""
    key = normalize_key(alias)
    if not key:
        return False
    stmt = (
        pg_insert(TeamAlias)
        .values(team_id=team_id, alias=key, source=source)
        .on_conflict_do_nothing(index_elements=[TeamAlias.alias])
        .returning(TeamAlias.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def upsert_team_page(session: AsyncSession, page: TeamPage) -> int:
    """팀 페이지 전체를 저장하고 teams.id 를 반환한다."""
    now = utcnow()
    values = dict(
        vlr_id=page.vlr_id,
        name=page.name,
        tag=page.tag,
        country_code=page.country_code,
        country_name=page.country_name,
        logo_url=page.logo_url,
        vlr_url=page.url,
        last_scraped_at=now,
    )
    stmt = pg_insert(Team).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Team.vlr_id],
        set_={
            **{k: stmt.excluded[k] for k in values if k != "vlr_id"},
            # 페이지에서 못 찾은 값은 기존 값을 유지
            "tag": func.coalesce(stmt.excluded.tag, Team.tag),
            "logo_url": func.coalesce(stmt.excluded.logo_url, Team.logo_url),
            "updated_at": now,
        },
    ).returning(Team.id)
    team_id: int = (await session.execute(stmt)).scalar_one()

    # --- 선수 레코드 (스태프 제외) ---
    player_ids: dict[int, int] = {}
    for entry in page.roster:
        if entry.player_vlr_id is None or entry.is_staff:
            continue
        p_values = dict(
            vlr_id=entry.player_vlr_id,
            nickname=entry.name,
            real_name=entry.real_name,
            country_code=entry.country_code,
            vlr_url=f"https://www.vlr.gg/player/{entry.player_vlr_id}",
            current_team_id=team_id,
        )
        p_stmt = pg_insert(Player).values(**p_values)
        p_stmt = p_stmt.on_conflict_do_update(
            index_elements=[Player.vlr_id],
            set_={
                "nickname": p_stmt.excluded.nickname,
                "real_name": func.coalesce(p_stmt.excluded.real_name, Player.real_name),
                "country_code": func.coalesce(p_stmt.excluded.country_code, Player.country_code),
                "vlr_url": p_stmt.excluded.vlr_url,
                "current_team_id": p_stmt.excluded.current_team_id,
                "updated_at": now,
            },
        ).returning(Player.id)
        player_ids[entry.player_vlr_id] = (await session.execute(p_stmt)).scalar_one()

    # 이 팀 소속이었지만 이번 로스터에 없는 선수 → 소속 해제
    await session.execute(
        update(Player)
        .where(Player.current_team_id == team_id, Player.vlr_id.not_in(list(player_ids) or [-1]))
        .values(current_team_id=None, updated_at=now)
    )

    # --- 로스터는 매번 통째로 교체 (이적·은퇴 반영) ---
    await session.execute(delete(TeamMember).where(TeamMember.team_id == team_id))
    seen: set[tuple[str, str]] = set()
    for entry in page.roster:
        key = (entry.name, entry.role)
        if key in seen:  # 같은 이름+역할 중복 방지 (UNIQUE 제약)
            continue
        seen.add(key)
        session.add(
            TeamMember(
                team_id=team_id,
                player_id=player_ids.get(entry.player_vlr_id) if entry.player_vlr_id else None,
                name=entry.name,
                real_name=entry.real_name,
                country_code=entry.country_code,
                role=entry.role,
                is_captain=entry.is_captain,
                sort_order=entry.sort_order,
            )
        )

    # --- 자동 별칭 (팀명, 태그) ---
    await add_team_alias(session, team_id, page.name, source="auto")
    if page.tag:
        await add_team_alias(session, team_id, page.tag, source="auto")

    # --- 팀 페이지의 경기 ---
    for item in page.upcoming + page.recent:
        await upsert_match(session, _row_from_team_item(item, team_id))

    await session.flush()
    return team_id


def _row_from_team_item(item: TeamMatchItem, team_id: int) -> dict[str, Any]:
    """팀 페이지는 항상 '이 팀'이 왼쪽이므로, URL 순서(team1-vs-team2)에 맞게 뒤집는다."""
    slug = item.url.rstrip("/").rsplit("/", 1)[-1]
    this_first = slug.startswith(slugify(item.team_name) + "-vs-")
    opp_first = slug.startswith(slugify(item.opponent_name) + "-vs-")
    swap = opp_first and not this_first

    a = dict(id=team_id, name=item.team_name, score=item.team_score)
    b = dict(id=None, name=item.opponent_name, score=item.opponent_score)
    t1, t2 = (b, a) if swap else (a, b)
    return dict(
        vlr_id=item.vlr_id,
        team1_id=t1["id"],
        team2_id=t2["id"],
        team1_name=t1["name"],
        team2_name=t2["name"],
        team1_score=t1["score"],
        team2_score=t2["score"],
        status=item.status,
        scheduled_at=item.scheduled_at,
        tournament_name=item.event_name,
        stage=item.stage,
        vlr_url=item.url,
    )


# ---------------------------------------------------------------------------
# 경기 / 대회 저장
# ---------------------------------------------------------------------------


async def upsert_match(session: AsyncSession, row: dict[str, Any]) -> None:
    now = utcnow()
    stmt = pg_insert(Match).values(**row)
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[Match.vlr_id],
        set_={
            "team1_name": ex.team1_name,
            "team2_name": ex.team2_name,
            "team1_id": func.coalesce(ex.team1_id, Match.team1_id),
            "team2_id": func.coalesce(ex.team2_id, Match.team2_id),
            "team1_score": func.coalesce(ex.team1_score, Match.team1_score),
            "team2_score": func.coalesce(ex.team2_score, Match.team2_score),
            "status": ex.status,
            "scheduled_at": func.coalesce(ex.scheduled_at, Match.scheduled_at),
            "tournament_name": func.coalesce(ex.tournament_name, Match.tournament_name),
            "stage": func.coalesce(ex.stage, Match.stage),
            "vlr_url": ex.vlr_url,
            "updated_at": now,
        },
    )
    await session.execute(stmt)


async def _team_ids_by_name(session: AsyncSession, names: set[str]) -> dict[str, int]:
    if not names:
        return {}
    lowered = {n.lower() for n in names}
    result = await session.execute(select(Team.id, Team.name).where(func.lower(Team.name).in_(lowered)))
    return {name.lower(): tid for tid, name in result.all()}


async def upsert_match_list(session: AsyncSession, items: list[MatchListItem]) -> int:
    """경기 목록 저장. 팀 이름이 DB에 있는 팀과 같으면 team_id 를 연결한다."""
    ids = await _team_ids_by_name(session, {i.team1_name for i in items} | {i.team2_name for i in items})
    for item in items:
        await upsert_match(
            session,
            dict(
                vlr_id=item.vlr_id,
                team1_id=ids.get(item.team1_name.lower()),
                team2_id=ids.get(item.team2_name.lower()),
                team1_name=item.team1_name,
                team2_name=item.team2_name,
                team1_score=item.team1_score,
                team2_score=item.team2_score,
                status=item.status,
                scheduled_at=item.scheduled_at,
                tournament_name=item.event_name,
                stage=item.stage,
                vlr_url=item.url,
            ),
        )
    await session.flush()
    return len(items)


def match_full_to_json(full: MatchFull) -> dict[str, Any]:
    """경기 상세 → JSON (matches.detail). 화면 표시에 필요한 값만 담는다."""
    d = full.detail

    def team(ref: Any) -> dict[str, Any] | None:
        return {"vlr_id": ref.vlr_id, "name": ref.name, "logo": ref.logo_url} if ref else None

    return {
        "status": full.status,
        "team1_score": full.team1_score,
        "team2_score": full.team2_score,
        "best_of": full.best_of,
        "team1": team(d.team1),
        "team2": team(d.team2),
        "event": {"name": d.event.name, "stage": d.event.stage, "logo": d.event.logo_url} if d.event else None,
        "maps": [asdict(m) for m in full.maps],
        "stats": {gid: [[asdict(p) for p in side] for side in sides] for gid, sides in full.stats.items()},
    }


async def save_match_full(session: AsyncSession, full: MatchFull, url: str | None = None) -> Match:
    """경기 상세를 저장(없으면 경기 행도 생성)하고 Match 를 돌려준다."""
    d = full.detail
    now = utcnow()

    tournament_id = await upsert_tournament(session, d.event) if d.event else None
    team_vlr_ids = [t.vlr_id for t in (d.team1, d.team2) if t and t.vlr_id]
    team_ids: dict[int, int] = {}
    if team_vlr_ids:
        rows = await session.execute(select(Team.vlr_id, Team.id).where(Team.vlr_id.in_(team_vlr_ids)))
        team_ids = dict(rows.all())

    values: dict[str, Any] = dict(
        vlr_id=full.vlr_id,
        team1_name=d.team1.name if d.team1 else "TBD",
        team2_name=d.team2.name if d.team2 else "TBD",
        team1_id=team_ids.get(d.team1.vlr_id) if d.team1 and d.team1.vlr_id else None,
        team2_id=team_ids.get(d.team2.vlr_id) if d.team2 and d.team2.vlr_id else None,
        team1_score=full.team1_score,
        team2_score=full.team2_score,
        status=full.status,
        scheduled_at=d.scheduled_at,
        tournament_id=tournament_id,
        tournament_name=d.event.name if d.event else None,
        stage=d.event.stage if d.event else None,
        vlr_url=url or f"https://www.vlr.gg/{full.vlr_id}",
        detail=match_full_to_json(full),
        detail_scraped_at=now,
    )
    stmt = pg_insert(Match).values(**values)
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[Match.vlr_id],
        set_={
            "team1_name": ex.team1_name,
            "team2_name": ex.team2_name,
            "team1_id": func.coalesce(ex.team1_id, Match.team1_id),
            "team2_id": func.coalesce(ex.team2_id, Match.team2_id),
            "team1_score": func.coalesce(ex.team1_score, Match.team1_score),
            "team2_score": func.coalesce(ex.team2_score, Match.team2_score),
            "status": ex.status,
            "scheduled_at": func.coalesce(ex.scheduled_at, Match.scheduled_at),
            "tournament_id": func.coalesce(ex.tournament_id, Match.tournament_id),
            "tournament_name": func.coalesce(ex.tournament_name, Match.tournament_name),
            "stage": func.coalesce(ex.stage, Match.stage),
            # 목록에서 저장한 전체 URL(슬러그 포함)이 있으면 유지
            "vlr_url": func.coalesce(Match.vlr_url, ex.vlr_url),
            "detail": ex.detail,
            "detail_scraped_at": ex.detail_scraped_at,
            "updated_at": now,
        },
    ).returning(Match.id)
    match_id = (await session.execute(stmt)).scalar_one()
    await session.flush()
    match = await session.get(Match, match_id, populate_existing=True)
    assert match is not None
    return match


async def get_match_by_vlr_id(session: AsyncSession, vlr_id: int) -> Match | None:
    result = await session.execute(select(Match).where(Match.vlr_id == vlr_id))
    return result.scalar_one_or_none()


async def get_team_matches(session: AsyncSession, team_id: int, limit: int = 10) -> list[Match]:
    """팀의 경기: 진행 중 → 예정(가까운 순) → 최근 종료(최신 순)."""
    involves = or_(Match.team1_id == team_id, Match.team2_id == team_id)
    live_upcoming = (
        await session.execute(
            select(Match)
            .where(involves, Match.status.in_(("live", "upcoming")))
            .order_by(case((Match.status == "live", 0), else_=1), Match.scheduled_at.asc().nulls_last())
            .limit(limit)
        )
    ).scalars().all()
    done = (
        await session.execute(
            select(Match)
            .where(involves, Match.status == "completed")
            .order_by(Match.scheduled_at.desc().nulls_last())
            .limit(limit)
        )
    ).scalars().all()
    return list(live_upcoming) + list(done)


async def upsert_tournament(session: AsyncSession, event: EventRef) -> int:
    stmt = pg_insert(Tournament).values(
        vlr_id=event.vlr_id, name=event.name, logo_url=event.logo_url, vlr_url=event.url
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Tournament.vlr_id],
        set_={
            "name": stmt.excluded.name,
            "logo_url": func.coalesce(stmt.excluded.logo_url, Tournament.logo_url),
            "updated_at": utcnow(),
        },
    ).returning(Tournament.id)
    return (await session.execute(stmt)).scalar_one()


# ---------------------------------------------------------------------------
# 조회 (Discord 명령어용)
# ---------------------------------------------------------------------------


@dataclass
class TeamLookup:
    team: Team | None
    candidates: list[Team]  # 확정하지 못했을 때 후보 (최대 5)


async def find_team(session: AsyncSession, query: str) -> TeamLookup:
    """팀 찾기. 잘못된 팀을 고르지 않도록 '확실한 경우'에만 확정한다.

    1) 별칭 정확히 일치 (젠지 → GEN.G)  2) 팀명 정확히 일치  3) 태그 정확히 일치(유일할 때)
    4) 팀명이 검색어로 시작하는 팀이 하나뿐일 때
    그 외에는 후보 목록만 돌려준다.
    """
    key = normalize_key(query)
    if not key:
        return TeamLookup(None, [])

    alias = await session.execute(select(TeamAlias.team_id).where(TeamAlias.alias == key))
    team_id = alias.scalar_one_or_none()
    if team_id is not None:
        return TeamLookup(await session.get(Team, team_id), [])

    q = query.strip().lower()
    exact = (await session.execute(select(Team).where(func.lower(Team.name) == q))).scalars().all()
    if len(exact) == 1:
        return TeamLookup(exact[0], [])

    by_tag = (await session.execute(select(Team).where(func.lower(Team.tag) == q))).scalars().all()
    if len(by_tag) == 1:
        return TeamLookup(by_tag[0], [])

    like = f"{q.replace('%', '').replace('_', '')}%"
    prefix = (
        await session.execute(
            select(Team).where(or_(func.lower(Team.name).like(like), func.lower(Team.tag).like(like))).limit(6)
        )
    ).scalars().all()
    if len(prefix) == 1:
        return TeamLookup(prefix[0], [])
    return TeamLookup(None, list(exact or by_tag or prefix)[:5])


@dataclass
class TeamDetail:
    team: Team
    members: list[TeamMember]
    recent: list[Match]
    upcoming: list[Match]


async def get_team_detail(session: AsyncSession, team_id: int, match_limit: int = 5) -> TeamDetail | None:
    team = await session.get(Team, team_id)
    if team is None:
        return None
    members = (
        await session.execute(
            select(TeamMember).where(TeamMember.team_id == team_id).order_by(TeamMember.sort_order)
        )
    ).scalars().all()

    involves = or_(Match.team1_id == team_id, Match.team2_id == team_id)
    recent = (
        await session.execute(
            select(Match)
            .where(involves, Match.status == "completed")
            .order_by(Match.scheduled_at.desc().nulls_last())
            .limit(match_limit)
        )
    ).scalars().all()
    upcoming = (
        await session.execute(
            select(Match)
            .where(involves, Match.status.in_(("upcoming", "live")))
            .order_by(Match.scheduled_at.asc().nulls_last())
            .limit(match_limit)
        )
    ).scalars().all()
    return TeamDetail(team, list(members), list(recent), list(upcoming))


async def get_upcoming_matches(session: AsyncSession, limit: int = 10) -> list[Match]:
    result = await session.execute(
        select(Match)
        .where(Match.status.in_(("upcoming", "live")))
        .options(selectinload(Match.team1), selectinload(Match.team2))
        .order_by(case((Match.status == "live", 0), else_=1), Match.scheduled_at.asc().nulls_last())  # live 먼저
        .limit(limit)
    )
    return list(result.scalars())
