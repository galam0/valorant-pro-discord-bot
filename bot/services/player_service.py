"""선수 관련 비즈니스 로직 (ProSettings 설정 + VLR 선수 정보)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from bot.database import repository as repo
from bot.database.database import db
from bot.scrapers.prosettings import PlayerPageNotFound, prosettings
from bot.utils.config import settings
from bot.worker_bridge import WorkerUnavailable

log = logging.getLogger("valobot.service.player")

SETTINGS_TTL = timedelta(hours=12)  # 선수 설정은 자주 안 바뀌므로 12시간 캐시
_locks: dict[str, asyncio.Lock] = {}


class PlayerNotFound(Exception):
    def __init__(self, query: str, candidates: list[repo.Player] | None = None) -> None:
        super().__init__(query)
        self.candidates = candidates or []


@dataclass
class PlayerResult:
    detail: repo.PlayerDetail
    guessed_from: str | None = None  # 오타 보정으로 찾았으면 원래 검색어
    stale: bool = False              # 갱신 실패로 예전 정보를 보여주는 경우
    no_settings: bool = False        # ProSettings에 이 선수 페이지가 없음
    fetch_error: str | None = None   # ProSettings 요청 자체가 실패한 이유 (차단, 네트워크 등)
    worker_offline: bool = False     # PC 수집기가 꺼져 있어서 못 가져옴


def _fresh(detail: repo.PlayerDetail) -> bool:
    s = detail.settings
    if s is not None and (s.raw or {}).get("manual"):
        return True  # 관리자가 직접 입력한 설정은 자동 갱신하지 않음 (ProSettings 요청 안 함)
    return s is not None and s.last_scraped_at is not None and repo.utcnow() - s.last_scraped_at < SETTINGS_TTL


async def refresh_player(nickname: str) -> repo.PlayerDetail:
    """ProSettings에서 선수 페이지를 가져와 저장. 없으면 PlayerPageNotFound."""
    pro = await prosettings.find_player(nickname)
    async with db.session() as s:
        player = await repo.save_pro_player(s, pro)
        await s.commit()
        detail = await repo.get_player_detail(s, player.id)
    assert detail is not None
    log.info("선수 설정 저장: %s (%s)", pro.nickname, pro.slug)
    return detail


async def get_player(query: str, *, force: bool = False) -> PlayerResult:
    """선수 조회. DB를 먼저 보고, 설정이 없거나 12시간이 지났으면 ProSettings에서 가져온다.

    예외: PlayerNotFound (후보가 있으면 candidates에 담김)
    """
    async with db.session() as s:
        lookup = await repo.find_player(s, query)
        detail = await repo.get_player_detail(s, lookup.player.id) if lookup.player else None

    guessed = query if lookup.guessed else None
    if detail is not None and not force and _fresh(detail):
        return PlayerResult(detail, guessed_from=guessed)

    if not settings.prosettings_enabled:
        # ProSettings는 꺼져 있음: DB에 있는 정보(관리자가 입력한 설정 포함)만 보여준다
        if detail is None:
            raise PlayerNotFound(query, lookup.candidates)
        return PlayerResult(detail, guessed_from=guessed, no_settings=detail.settings is None)

    # ProSettings에서 찾을 이름: DB에서 찾았으면 그 닉네임(또는 저장된 slug), 아니면 검색어 그대로
    name = (detail.player.prosettings_slug or detail.player.nickname) if detail else query
    lock = _locks.setdefault(name.lower(), asyncio.Lock())
    async with lock:
        try:
            fresh = await refresh_player(name)
            return PlayerResult(fresh, guessed_from=guessed)
        except PlayerPageNotFound:
            if detail is not None:
                # VLR 선수지만 ProSettings에 페이지가 없음 → 있는 정보만 보여준다
                return PlayerResult(detail, guessed_from=guessed, no_settings=detail.settings is None)
            raise PlayerNotFound(query, lookup.candidates) from None
        except Exception as exc:
            offline = isinstance(exc, WorkerUnavailable)
            log.warning("선수 설정 갱신 실패 (%s): %s: %s", name, type(exc).__name__, exc)
            if detail is not None:
                return PlayerResult(detail, guessed_from=guessed, stale=detail.settings is not None,
                                    no_settings=detail.settings is None, fetch_error=str(exc),
                                    worker_offline=offline)
            raise
