"""일반 유저 전적 (HenrikDev 비공식 API). 로그인·비밀번호 없이 공개된 '이름#태그' 조회만 한다.

- 키는 환경변수 HENRIK_API_KEY. 요청은 동시에 2개까지, 같은 조회는 2분간 캐시한다.
- 비공식 API라 응답 형식이 바뀌거나 끊길 수 있다. 그래서 파싱은 모르는 값이 와도 죽지 않게 짠다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import aiohttp

from bot.utils.config import settings

log = logging.getLogger("valobot.riot")

BASE = "https://api.henrikdev.xyz/valorant"
REGIONS = ("kr", "ap", "na", "eu")
RECENT = 5
CACHE_TTL = 120
KST = timezone(timedelta(hours=9))

TIER_KO = ("아이언", "브론즈", "실버", "골드", "플래티넘", "다이아몬드", "초월자", "불멸")
MODE_KO = {
    "competitive": "경쟁전", "unrated": "일반", "swiftplay": "신속전", "spikerush": "스파이크 러시",
    "deathmatch": "데스매치", "premier": "프리미어", "custom": "커스텀", "snowball": "눈싸움",
    "replication": "복제", "hurm": "팀 데스매치", "teamdeathmatch": "팀 데스매치",
}
MAP_KO = {
    "ascent": "어센트", "bind": "바인드", "haven": "헤이븐", "split": "스플릿", "icebox": "아이스박스",
    "breeze": "브리즈", "fracture": "프랙처", "pearl": "펄", "lotus": "로터스", "sunset": "선셋",
    "abyss": "어비스", "corrode": "코로드",
}


class RiotError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류 메시지."""


class NotConfigured(RiotError):
    pass


class PlayerNotFound(RiotError):
    pass


def tier_ko(tier_id: int | None) -> str:
    """티어 번호(0~27)를 한글 이름으로. 3=아이언 1, 27=래디언트."""
    if tier_id is None or tier_id < 3:
        return "언랭크"
    if tier_id >= 27:
        return "래디언트"
    base, num = divmod(tier_id - 3, 3)
    return f"{TIER_KO[min(base, len(TIER_KO) - 1)]} {num + 1}"


def parse_riot_id(text: str) -> tuple[str, str]:
    """'이름#태그' → (이름, 태그). 형식이 틀리면 RiotError."""
    name, sep, tag = (text or "").strip().rpartition("#")
    name, tag = name.strip(), tag.strip()
    if not sep or not name or not tag or len(name) > 16 or len(tag) > 5:
        raise RiotError("라이엇 ID는 `이름#태그` 형식으로 입력해주세요. (예: `Hide on bush#KR1`)")
    return name, tag


@dataclass
class MatchRow:
    map_name: str
    agent_id: str
    agent: str
    mode: str
    won: bool | None
    rounds_won: int
    rounds_lost: int
    kills: int
    deaths: int
    assists: int
    hs_pct: float
    adr: float
    started: datetime | None

    @property
    def kd(self) -> float:
        return self.kills / max(1, self.deaths)


@dataclass
class UserStats:
    name: str
    tag: str
    region: str
    level: int | None = None
    tier_id: int | None = None
    rr: int | None = None
    last_change: int | None = None
    peak_id: int | None = None
    peak_season: str = ""
    matches: list[MatchRow] = field(default_factory=list)

    @property
    def wins(self) -> int:
        return sum(1 for m in self.matches if m.won)

    @property
    def losses(self) -> int:
        return sum(1 for m in self.matches if m.won is False)

    @property
    def avg_kd(self) -> float:
        k, d = sum(m.kills for m in self.matches), sum(m.deaths for m in self.matches)
        return k / max(1, d)

    @property
    def avg_hs(self) -> float:
        return sum(m.hs_pct for m in self.matches) / len(self.matches) if self.matches else 0.0

    @property
    def avg_adr(self) -> float:
        return sum(m.adr for m in self.matches) / len(self.matches) if self.matches else 0.0


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_mmr(data: dict, stats: UserStats) -> None:
    cur = (data or {}).get("current") or {}
    stats.tier_id = _int((cur.get("tier") or {}).get("id"), None) if cur.get("tier") else None
    stats.rr = _int(cur.get("rr"), None) if cur.get("rr") is not None else None
    stats.last_change = _int(cur.get("last_change"), None) if cur.get("last_change") is not None else None
    peak = (data or {}).get("peak") or {}
    if peak.get("tier"):
        stats.peak_id = _int(peak["tier"].get("id"), None)
        stats.peak_season = str((peak.get("season") or {}).get("short") or "").upper()


def parse_match(m: dict, puuid: str, name: str, tag: str) -> MatchRow | None:
    """경기 하나에서 '내' 기록만 뽑는다. 내가 없으면 None."""
    players = m.get("players") or []
    me = next((p for p in players if puuid and p.get("puuid") == puuid), None)
    if me is None:
        me = next((p for p in players if str(p.get("name", "")).lower() == name.lower()
                   and str(p.get("tag", "")).lower() == tag.lower()), None)
    if me is None:
        return None
    st = me.get("stats") or {}
    shots = _int(st.get("headshots")) + _int(st.get("bodyshots")) + _int(st.get("legshots"))
    mine = next((t for t in (m.get("teams") or []) if str(t.get("team_id", "")).lower() == str(me.get("team_id", "")).lower()), None)
    rounds = (mine or {}).get("rounds") or {}
    rw, rl = _int(rounds.get("won")), _int(rounds.get("lost"))
    played = max(1, rw + rl)
    meta = m.get("metadata") or {}
    queue = meta.get("queue") or {}
    qid = str(queue.get("id") or "").lower()
    started = None
    try:
        started = datetime.fromisoformat(str(meta.get("started_at")).replace("Z", "+00:00")).astimezone(KST)
    except (TypeError, ValueError):
        pass
    map_name = str((meta.get("map") or {}).get("name") or "?")
    won = mine.get("won") if mine is not None and isinstance(mine.get("won"), bool) else None
    return MatchRow(
        map_name=MAP_KO.get(map_name.lower(), map_name),
        agent_id=str((me.get("agent") or {}).get("id") or ""),
        agent=str((me.get("agent") or {}).get("name") or "?"),
        mode=MODE_KO.get(qid, queue.get("name") or qid or "?"),
        won=won, rounds_won=rw, rounds_lost=rl,
        kills=_int(st.get("kills")), deaths=_int(st.get("deaths")), assists=_int(st.get("assists")),
        hs_pct=_int(st.get("headshots")) / shots * 100 if shots else 0.0,
        adr=_int((st.get("damage") or {}).get("dealt")) / played,
        started=started,
    )


# --- 요청 -------------------------------------------------------------------

_sem = asyncio.Semaphore(2)
_cache: dict[tuple, tuple[float, UserStats]] = {}
_session: aiohttp.ClientSession | None = None


async def _get(path: str, params: dict | None = None) -> dict:
    global _session
    key = settings.henrik_api_key
    if not key:
        raise NotConfigured("유저 전적 기능이 아직 켜져 있지 않아요. (관리자: HENRIK_API_KEY 설정 필요)")
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                         headers={"Authorization": key, "User-Agent": "ValoProBot"})
    async with _sem:
        try:
            async with _session.get(f"{BASE}{path}", params=params) as resp:
                if resp.status == 404:
                    raise PlayerNotFound("해당 라이엇 ID를 찾을 수 없어요. 이름과 태그, 지역을 확인해주세요.")
                if resp.status == 429:
                    raise RiotError("요청이 너무 많아요. 잠시 후 다시 시도해주세요.")
                if resp.status in (401, 403):
                    log.error("Henrik API 키가 거부됨 (%s)", resp.status)
                    raise RiotError("유저 전적 서버 인증에 실패했어요. 관리자에게 알려주세요.")
                if resp.status >= 400:
                    log.warning("Henrik API 오류 %s: %s", resp.status, path.split("/")[1] if "/" in path else path)
                    raise RiotError("유저 전적 서버가 응답하지 않아요. 잠시 후 다시 시도해주세요.")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Henrik API 연결 실패: %s", type(exc).__name__)
            raise RiotError("유저 전적 서버에 연결하지 못했어요. 잠시 후 다시 시도해주세요.") from exc


async def fetch_user(name: str, tag: str, region: str = "kr") -> UserStats:
    region = region if region in REGIONS else "kr"
    ck = (name.lower(), tag.lower(), region)
    hit = _cache.get(ck)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]

    from urllib.parse import quote
    n, t = quote(name, safe=""), quote(tag, safe="")
    mmr_r, match_r = await asyncio.gather(
        _get(f"/v3/mmr/{region}/pc/{n}/{t}"),
        _get(f"/v4/matches/{region}/pc/{n}/{t}", {"size": RECENT, "mode": "competitive"}),
        return_exceptions=True,
    )
    if isinstance(mmr_r, PlayerNotFound) or isinstance(match_r, PlayerNotFound):
        raise PlayerNotFound("해당 라이엇 ID를 찾을 수 없어요. 이름과 태그, 지역을 확인해주세요.")
    if isinstance(mmr_r, BaseException) and isinstance(match_r, BaseException):
        raise mmr_r if isinstance(mmr_r, RiotError) else RiotError("유저 전적을 불러오지 못했어요.")
    stats = UserStats(name=name, tag=tag, region=region)
    puuid = ""
    if not isinstance(mmr_r, BaseException):
        d = mmr_r.get("data") or {}
        acc = d.get("account") or {}
        stats.name, stats.tag, puuid = acc.get("name") or name, acc.get("tag") or tag, acc.get("puuid") or ""
        parse_mmr(d, stats)
    if not isinstance(match_r, BaseException):
        for m in (match_r.get("data") or [])[:RECENT]:
            row = parse_match(m, puuid, name, tag)
            if row:
                stats.matches.append(row)
        for m in (match_r.get("data") or [])[:1]:
            me = next((p for p in m.get("players") or [] if p.get("puuid") == puuid), None)
            if me:
                stats.level = _int(me.get("account_level"), None) if me.get("account_level") is not None else None
    else:
        log.info("최근 경기 조회 실패(랭크만 표시): %s", type(match_r).__name__)

    if len(_cache) > 200:
        _cache.clear()
    _cache[ck] = (time.monotonic(), stats)
    return stats


# --- 티어 아이콘 (valorant-api.com, 하루 캐시) ----------------------------------

_tier_icons: tuple[float, dict[int, str]] | None = None


async def tier_icon_url(tier_id: int | None) -> str | None:
    global _tier_icons
    if tier_id is None:
        return None
    if _tier_icons is None or time.monotonic() - _tier_icons[0] > 86400:
        urls: dict[int, str] = {}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.get("https://valorant-api.com/v1/competitivetiers") as r:
                    data = (await r.json(content_type=None)).get("data") or []
            for t in (data[-1].get("tiers") if data else []) or []:
                if t.get("largeIcon"):
                    urls[_int(t.get("tier"))] = t["largeIcon"]
        except Exception as exc:
            log.info("티어 아이콘 목록 실패: %s", type(exc).__name__)
        _tier_icons = (time.monotonic(), urls)
    return _tier_icons[1].get(tier_id)


def agent_icon_url(agent_id: str) -> str | None:
    return f"https://media.valorant-api.com/agents/{agent_id}/displayicon.png" if agent_id else None


async def close() -> None:
    if _session is not None and not _session.closed:
        await _session.close()
