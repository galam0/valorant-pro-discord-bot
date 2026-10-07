"""두 팀 비교: DB에 저장된 정보만 사용한다 (사이트에 요청하지 않음)."""

from __future__ import annotations

from dataclasses import dataclass

from bot.database import repository as repo
from bot.database.database import db
from bot.services import team_service


class CompareError(Exception):
    """사용자에게 그대로 보여줄 수 있는 메시지를 담는다."""


@dataclass
class CompareResult:
    a: repo.TeamDetail
    b: repo.TeamDetail
    h2h: list[repo.Match]  # 종료된 맞대결 (최신순, DB에 저장된 경기만)


async def _resolve(query: str) -> repo.TeamDetail:
    detail, candidates = await team_service.get_team(query)
    if detail is not None:
        return detail
    if candidates:
        names = ", ".join(f"`{t.name}`" for t in candidates)
        raise CompareError(f"'{query}'에 해당하는 팀을 하나로 특정하지 못했습니다.\n혹시 이 팀인가요? {names}")
    raise CompareError(f"'{query}' 팀을 찾을 수 없습니다.\n아직 수집되지 않은 팀일 수 있어요. (관리자: `/관리 팀갱신 {query}`)")


async def compare(query_a: str, query_b: str) -> CompareResult:
    a = await _resolve(query_a)
    b = await _resolve(query_b)
    if a.team.id == b.team.id:
        raise CompareError("서로 다른 두 팀을 입력해주세요.")
    async with db.session() as s:
        h2h = await repo.get_head_to_head(s, a.team.id, b.team.id)
    return CompareResult(a, b, h2h)
