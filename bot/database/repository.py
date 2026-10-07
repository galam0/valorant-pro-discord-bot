"""DB 접근 함수 모음.

명령어(UI)나 스크래퍼는 SQL을 직접 쓰지 않고 이 모듈의 함수만 호출한다.
Phase 3 이후 팀/선수/경기 조회·upsert 함수가 여기에 추가된다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

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
    run.finished_at = datetime.now(timezone.utc)
    await session.flush()


async def get_last_scrape_runs(session: AsyncSession, limit: int = 10) -> list[ScrapeRun]:
    result = await session.execute(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit))
    return list(result.scalars())
