"""발로란트 개인 상점 연동 상태 DB 함수 (호출하는 쪽의 세션 안에서 실행, commit 은 호출한 쪽)."""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ValorantShopLink


async def get(session: AsyncSession, user_id: int) -> ValorantShopLink | None:
    return (await session.execute(select(ValorantShopLink).where(ValorantShopLink.discord_user_id == user_id))).scalar_one_or_none()


async def mark_linked(session: AsyncSession, user_id: int, provider: str) -> None:
    """허용된 제공자의 연동 절차가 성공한 뒤에만 부른다. 동시에 두 번 불려도 한 행만 남는다(upsert)."""
    stmt = pg_insert(ValorantShopLink).values(discord_user_id=user_id, status="linked", provider=provider,
                                              linked_at=func.now(), last_error=None)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[ValorantShopLink.discord_user_id],
        set_={"status": "linked", "provider": provider, "linked_at": func.now(), "last_error": None,
              "updated_at": func.now()}))


async def unlink(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(delete(ValorantShopLink).where(ValorantShopLink.discord_user_id == user_id))
    return bool(result.rowcount)


async def record_check(session: AsyncSession, user_id: int, error: str | None = None, *, expired: bool = False) -> None:
    """마지막 조회 시각·오류 종류(짧은 코드)만 기록한다. 인증 정보나 응답 내용은 기록하지 않는다."""
    values: dict = {"last_checked_at": func.now(), "last_error": (error or None) and error[:60], "updated_at": func.now()}
    if expired:
        values["status"] = "expired"
    await session.execute(update(ValorantShopLink).where(ValorantShopLink.discord_user_id == user_id).values(**values))
