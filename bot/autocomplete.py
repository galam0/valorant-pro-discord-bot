"""슬래시 명령어 자동완성 (팀·선수·대회 이름).

자동완성은 글자를 칠 때마다 3초 안에 답해야 하므로 DB를 매번 보지 않고 메모리 목록을 쓴다.
- 목록은 1시간마다 갱신 (Neon 자동 중지를 깨우지 않도록 요청이 있을 때만, 그것도 느리면 백그라운드로)
- 목록이 아직 없으면 빈 결과를 돌려주고(사용자는 그냥 직접 입력하면 됨) 뒤에서 불러온다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from discord import app_commands
import discord


log = logging.getLogger("valobot.autocomplete")


def normalize_key(text: str) -> str:
    """repository.normalize_key 와 같은 규칙 (소문자, 영문·숫자·한글만)."""
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


TTL = 3600
MAX_CHOICES = 25
# 대회 이름 자동완성 후보 (한국어 → event_service.to_query 가 영어 검색어로 바꿔 줌)
EVENT_SUGGESTIONS = [
    "챔피언스", "마스터스", "퍼시픽", "아메리카스", "EMEA", "차이나", "챌린저스",
    "Masters", "Champions", "VCT Pacific", "VCT Americas", "VCT EMEA", "VCT China",
]


@dataclass
class _Entry:
    label: str                      # 선택지에 보일 이름 (= 입력될 값)
    keys: list[str] = field(default_factory=list)  # 정규화된 검색 키 (이름, 태그, 별칭)


@dataclass
class _Index:
    teams: list[_Entry] = field(default_factory=list)
    players: list[_Entry] = field(default_factory=list)
    schedule_events: list[_Entry] = field(default_factory=list)  # 최근·예정 경기가 있는 대회
    loaded_at: float = 0.0


_index = _Index()
_loading: asyncio.Task | None = None


async def _load() -> None:
    from sqlalchemy import select

    from bot.database.database import db

    from datetime import datetime, timedelta, timezone

    from bot.database.models import Match, Player, Team, TeamAlias

    async with db.session() as s:
        teams = (await s.execute(select(Team.id, Team.name, Team.tag))).all()
        aliases = (await s.execute(select(TeamAlias.team_id, TeamAlias.alias))).all()
        players = (await s.execute(select(Player.nickname))).scalars().all()
        now = datetime.now(timezone.utc)
        names = (await s.execute(
            select(Match.tournament_name).where(
                Match.tournament_name.is_not(None),
                Match.scheduled_at.between(now - timedelta(days=3), now + timedelta(days=7)),
            ).distinct()
        )).scalars().all()
    by_team: dict[int, list[str]] = {}
    for tid, alias in aliases:
        by_team.setdefault(tid, []).append(alias)
    t_entries = []
    for tid, name, tag in teams:
        keys = {normalize_key(name), *by_team.get(tid, [])}
        if tag:
            keys.add(normalize_key(tag))
        t_entries.append(_Entry(name, [k for k in keys if k]))
    seen: set[str] = set()
    p_entries = []
    for nick in players:
        if nick.lower() in seen:
            continue
        seen.add(nick.lower())
        p_entries.append(_Entry(nick, [normalize_key(nick)]))
    _index.teams = sorted(t_entries, key=lambda e: e.label.lower())
    _index.players = sorted(p_entries, key=lambda e: e.label.lower())
    _index.schedule_events = sorted((_Entry(n, [normalize_key(n)]) for n in names), key=lambda e: e.label.lower())
    _index.loaded_at = time.monotonic()
    log.info("자동완성 목록 갱신: 팀 %d, 선수 %d", len(t_entries), len(p_entries))


def _ensure_loaded() -> None:
    """목록이 없거나 오래됐으면 백그라운드로 갱신 시작 (기다리지 않음)."""
    global _loading
    from bot.database.database import db

    if not db.configured:
        return
    if _loading is not None and not _loading.done():
        return
    if _index.loaded_at and time.monotonic() - _index.loaded_at < TTL:
        return

    async def run() -> None:
        try:
            await _load()
        except Exception:
            log.exception("자동완성 목록 갱신 실패")
            _index.loaded_at = time.monotonic() - TTL + 60  # 1분 뒤 재시도

    _loading = asyncio.create_task(run())


def match(entries: list[_Entry], current: str, limit: int = MAX_CHOICES) -> list[str]:
    """입력 글자로 후보를 고른다. 앞부분 일치 → 포함 순."""
    q = normalize_key(current)
    if not q:
        return [e.label for e in entries[:limit]]
    starts, contains = [], []
    for e in entries:
        if any(k.startswith(q) for k in e.keys):
            starts.append(e.label)
        elif any(q in k for k in e.keys):
            contains.append(e.label)
    return (starts + contains)[:limit]


def _choices(labels: list[str]) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=l[:100], value=l[:100]) for l in labels]


async def team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    _ensure_loaded()
    return _choices(match(_index.teams, current))


async def player_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    _ensure_loaded()
    return _choices(match(_index.players, current))


async def event_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    q = current.strip().lower()
    labels = [e for e in EVENT_SUGGESTIONS if q in e.lower()] if q else EVENT_SUGGESTIONS
    return _choices(labels[:MAX_CHOICES])


async def schedule_event_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """/일정 의 대회 선택 — 최근·예정 경기가 있는 대회만 보여 준다."""
    _ensure_loaded()
    return _choices(match(_index.schedule_events, current))
