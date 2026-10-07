"""VLR.gg 스크래퍼.

VLR.gg는 공개 API가 없으므로 HTML을 파싱한다. 선택자는 2026-10 실제 페이지에서 확인한 구조 기준.
사이트 구조가 바뀌면 이 파일의 parse_* 함수만 고치면 된다 (DB/명령어 코드는 영향 없음).

확인한 페이지와 핵심 선택자
- 팀 검색   /search/?q=T1&type=teams      a.search-item (href=/search/r/team/{id}/idx)
- 팀       /team/{id}                     .team-header, .team-roster-item, h2.wf-label + a.m-item
- 경기 목록 /matches, /matches/results     .wf-label.mod-large(날짜) + a.match-item
- 경기 상세 /{match_id}                    .moment-tz-convert[data-utc-ts], a.match-header-link, a.match-header-event
- robots.txt: /search/auto, /rr/ 만 금지 → 위 경로는 모두 허용

시간대 주의
- 목록 페이지의 시각은 요청한 서버 IP 위치 기준 시간대로 표시된다 (Render 서버 위치에 따라 달라짐).
- 경기 상세의 data-utc-ts 는 이름과 달리 미국 동부 시간(America/New_York)이다.
  (확인: data-utc-ts="2026-10-07 08:00:00" 이 같은 페이지에서 "9:00 PM KST"로 표시됨 → UTC-4)
- 그래서 경기 1개의 상세 페이지로 목록 시간대의 오프셋을 측정(보정)한 뒤 목록 전체에 적용한다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from bot.scrapers.http import HttpClient, http_client
from bot.utils.korean import STAFF_ROLES, VLR_ROLE_TAG

log = logging.getLogger("valobot.scraper.vlr")

BASE_URL = "https://www.vlr.gg"
VLR_SOURCE_TZ = ZoneInfo("America/New_York")
_PLACEHOLDER_IMG = ("/img/vlr/tmp/", "/img/base/ph/")


class ParseError(Exception):
    """페이지 구조가 예상과 달라 필요한 정보를 찾지 못함 (사이트 구조 변경 가능성)."""


# ---------------------------------------------------------------------------
# 결과 데이터 (DB 모델과 분리: 스크래퍼는 DB를 모른다)
# ---------------------------------------------------------------------------


@dataclass
class TeamSearchResult:
    vlr_id: int
    name: str
    logo_url: str | None
    inactive: bool


@dataclass
class RosterEntry:
    name: str
    role: str                     # player / substitute / inactive / head_coach / coach / ...
    player_vlr_id: int | None
    real_name: str | None
    country_code: str | None
    photo_url: str | None
    is_captain: bool
    sort_order: int

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES


@dataclass
class TeamMatchItem:
    """팀 페이지의 경기 한 줄. 항상 '이 팀'이 왼쪽(team)이다."""

    vlr_id: int
    url: str
    event_name: str | None
    stage: str | None
    team_name: str
    team_tag: str | None
    team_logo: str | None
    opponent_name: str
    opponent_tag: str | None
    opponent_logo: str | None
    team_score: int | None
    opponent_score: int | None
    status: str                   # upcoming / live / completed
    local_dt: datetime | None     # 목록 표시 시각 (시간대 미보정)
    scheduled_at: datetime | None = None  # UTC (보정 후)


@dataclass
class TeamPage:
    vlr_id: int
    name: str
    tag: str | None
    country_code: str | None
    country_name: str | None
    logo_url: str | None
    url: str
    roster: list[RosterEntry] = field(default_factory=list)
    upcoming: list[TeamMatchItem] = field(default_factory=list)
    recent: list[TeamMatchItem] = field(default_factory=list)


@dataclass
class MatchListItem:
    vlr_id: int
    url: str
    team1_name: str
    team2_name: str
    team1_country: str | None
    team2_country: str | None
    team1_score: int | None
    team2_score: int | None
    winner: int | None            # 1 / 2 / None
    status: str                   # upcoming / live / completed
    event_name: str | None
    stage: str | None
    event_logo: str | None
    local_dt: datetime | None
    scheduled_at: datetime | None = None


@dataclass
class MatchTeamRef:
    vlr_id: int | None
    name: str
    logo_url: str | None


@dataclass
class EventRef:
    vlr_id: int
    name: str
    stage: str | None
    logo_url: str | None
    url: str


@dataclass
class MatchDetail:
    vlr_id: int
    scheduled_at: datetime | None  # UTC
    team1: MatchTeamRef | None
    team2: MatchTeamRef | None
    event: EventRef | None


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _text(el: Tag | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _own_text(el: Tag | None) -> str:
    """자식 태그를 제외한 직접 텍스트 (예: 팀명 옆 '(inactive since ...)' 제외)."""
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.find_all(string=True, recursive=False))).strip()


def abs_url(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_URL + href
    return href


def image_url(src: str | None) -> str | None:
    """VLR 이미지 주소 → 절대 URL. 기본(빈) 이미지면 None (Discord에서 fallback 처리)."""
    if not src or any(p in src for p in _PLACEHOLDER_IMG):
        return None
    return abs_url(src)


def _flag_code(el: Tag | None) -> str | None:
    if el is None:
        return None
    flag = el.select_one(".flag")
    if flag is None:
        return None
    for cls in flag.get("class", []):
        if cls.startswith("mod-") and len(cls) <= 8:
            return cls[4:].lower()
    return None


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def _id_from(pattern: str, href: str | None) -> int | None:
    if not href:
        return None
    m = re.search(pattern, href)
    return int(m.group(1)) if m else None


def _parse_ampm_time(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap]m)", text, re.I)
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3).lower() == "pm":
        hour += 12
    return hour, minute


# ---------------------------------------------------------------------------
# 파서 (HTML → 데이터) — 네트워크와 무관해서 단독 테스트 가능
# ---------------------------------------------------------------------------


def parse_search_teams(html: str) -> list[TeamSearchResult]:
    results: list[TeamSearchResult] = []
    for a in _soup(html).select("a.search-item"):
        vlr_id = _id_from(r"/team/(\d+)", a.get("href"))
        if vlr_id is None:
            continue
        title = a.select_one(".search-item-title")
        name = _own_text(title) or _text(title)
        if not name:
            continue
        img = a.select_one(".search-item-thumb img")
        results.append(
            TeamSearchResult(
                vlr_id=vlr_id,
                name=name,
                logo_url=image_url(img.get("src") if img else None),
                inactive="inactive" in _text(title).lower(),
            )
        )
    return results


def _parse_team_match_item(a: Tag) -> TeamMatchItem | None:
    href = a.get("href") or ""
    vlr_id = _id_from(r"^/(\d+)/", href)
    if vlr_id is None:
        return None

    event_el = a.select_one(".m-item-event")
    event_name = _text(event_el.find("div")) if event_el else ""
    stage = _text(event_el)
    if event_name and stage.startswith(event_name):
        stage = stage[len(event_name):].strip()

    teams = a.select(".m-item-team")
    logos = a.select(".m-item-logo img")
    if len(teams) < 2:
        return None

    result = a.select_one(".m-item-result")
    classes = set(result.get("class", [])) if result else set()
    if "mod-live" in classes:
        status = "live"
    elif classes & {"mod-win", "mod-loss", "mod-draw", "mod-tie"}:
        status = "completed"
    else:
        status = "upcoming"
    scores = [_int_or_none(_text(s)) for s in result.select("span")] if result else []

    date_text = _text(a.select_one(".m-item-date"))
    local_dt: datetime | None = None
    dm = re.search(r"(\d{4})/(\d{2})/(\d{2})", date_text)
    tm = _parse_ampm_time(date_text)
    if dm and tm:
        local_dt = datetime(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)), tm[0], tm[1])

    return TeamMatchItem(
        vlr_id=vlr_id,
        url=abs_url(href.split("?")[0]) or "",
        event_name=event_name or None,
        stage=stage or None,
        team_name=_text(teams[0].select_one(".m-item-team-name")),
        team_tag=_text(teams[0].select_one(".m-item-team-tag")) or None,
        team_logo=image_url(logos[0].get("src")) if len(logos) > 0 else None,
        opponent_name=_text(teams[1].select_one(".m-item-team-name")),
        opponent_tag=_text(teams[1].select_one(".m-item-team-tag")) or None,
        opponent_logo=image_url(logos[1].get("src")) if len(logos) > 1 else None,
        team_score=scores[0] if len(scores) >= 2 else None,
        opponent_score=scores[1] if len(scores) >= 2 else None,
        status=status,
        local_dt=local_dt,
    )


def parse_team_page(html: str, vlr_id: int) -> TeamPage:
    soup = _soup(html)
    header = soup.select_one(".team-header")
    name = _text(soup.select_one(".team-header-name h1"))
    if header is None or not name:
        raise ParseError(f"팀 페이지 구조를 인식하지 못했습니다 (team {vlr_id})")

    country_el = header.select_one(".team-header-country")
    logo = header.select_one(".team-header-logo img")

    # --- 로스터: 'players' / 'staff' 라벨 아래에 항목이 순서대로 나온다 ---
    roster: list[RosterEntry] = []
    first_item = soup.select_one(".team-roster-item")
    card = first_item.find_parent(class_="wf-card") if first_item else None
    if card is not None:
        section = "players"
        for el in card.select(".wf-module-label, .team-roster-item"):
            classes = el.get("class", [])
            if "wf-module-label" in classes:
                section = _text(el).lower()
                continue
            alias = el.select_one(".team-roster-item-name-alias")
            nick = _text(alias)
            if not nick:
                continue
            tag = _text(el.select_one(".team-roster-item-name-role")).lower()
            if tag:
                role = VLR_ROLE_TAG.get(tag, "staff" if section == "staff" else tag.replace(" ", "_"))
            else:
                role = "staff" if section == "staff" else "player"
            link = el.select_one("a")
            photo = el.select_one(".team-roster-item-img img")
            roster.append(
                RosterEntry(
                    name=nick,
                    role=role,
                    player_vlr_id=_id_from(r"/player/(\d+)", link.get("href") if link else None),
                    real_name=_text(el.select_one(".team-roster-item-name-real")) or None,
                    country_code=_flag_code(alias),
                    photo_url=image_url(photo.get("src") if photo else None),
                    is_captain=alias.select_one(".fa-star") is not None,
                    sort_order=len(roster),
                )
            )

    # --- 경기: h2.wf-label('Upcoming matches' / 'Recent Results') 바로 다음 요소 ---
    upcoming: list[TeamMatchItem] = []
    recent: list[TeamMatchItem] = []
    for label in soup.select("h2.wf-label"):
        label_text = _text(label).lower()
        target = upcoming if "upcoming" in label_text else recent if "recent" in label_text else None
        container = label.find_next_sibling()
        if target is None or container is None:
            continue
        for a in container.select("a.m-item"):
            item = _parse_team_match_item(a)
            if item:
                target.append(item)

    tag = next((m.team_tag for m in (upcoming + recent) if m.team_tag), None)

    return TeamPage(
        vlr_id=vlr_id,
        name=name,
        tag=tag,
        country_code=_flag_code(country_el),
        country_name=_text(country_el) or None,
        logo_url=image_url(logo.get("src") if logo else None),
        url=f"{BASE_URL}/team/{vlr_id}",
        roster=roster,
        upcoming=upcoming,
        recent=recent,
    )


def parse_matches_list(html: str) -> list[MatchListItem]:
    """/matches, /matches/results 공용."""
    items: list[MatchListItem] = []
    current_date: datetime | None = None

    for el in _soup(html).select(".wf-label.mod-large, a.match-item"):
        classes = el.get("class", [])
        if "match-item" not in classes:
            date_text = _own_text(el) or _text(el)
            try:
                current_date = datetime.strptime(date_text, "%a, %B %d, %Y")
            except ValueError:
                current_date = None
            continue

        href = el.get("href") or ""
        vlr_id = _id_from(r"^/(\d+)/", href)
        teams = el.select(".match-item-vs-team")
        if vlr_id is None or len(teams) < 2:
            continue

        status_text = _text(el.select_one(".ml-status")).lower()
        status = "live" if status_text == "live" else "completed" if status_text == "completed" else "upcoming"

        event_el = el.select_one(".match-item-event")
        series = _text(event_el.select_one(".match-item-event-series")) if event_el else ""
        event_name = _text(event_el)
        if series and event_name.startswith(series):
            event_name = event_name[len(series):].strip()

        local_dt = None
        tm = _parse_ampm_time(_text(el.select_one(".match-item-time")))
        if current_date and tm:
            local_dt = current_date.replace(hour=tm[0], minute=tm[1])

        icon = el.select_one(".match-item-icon img")
        winner = 1 if "mod-winner" in teams[0].get("class", []) else 2 if "mod-winner" in teams[1].get("class", []) else None

        items.append(
            MatchListItem(
                vlr_id=vlr_id,
                url=abs_url(href) or "",
                team1_name=_text(teams[0].select_one(".match-item-vs-team-name")),
                team2_name=_text(teams[1].select_one(".match-item-vs-team-name")),
                team1_country=_flag_code(teams[0]),
                team2_country=_flag_code(teams[1]),
                team1_score=_int_or_none(_text(teams[0].select_one(".match-item-vs-team-score"))),
                team2_score=_int_or_none(_text(teams[1].select_one(".match-item-vs-team-score"))),
                winner=winner,
                status=status,
                event_name=event_name or None,
                stage=series or None,
                event_logo=image_url(icon.get("src") if icon else None),
                local_dt=local_dt,
            )
        )
    return items


def parse_match_page(html: str, vlr_id: int) -> MatchDetail:
    soup = _soup(html)

    scheduled_at = None
    ts_el = soup.select_one(".match-header-date [data-utc-ts]")
    if ts_el is not None:
        try:
            naive = datetime.strptime(ts_el["data-utc-ts"].strip(), "%Y-%m-%d %H:%M:%S")
            scheduled_at = naive.replace(tzinfo=VLR_SOURCE_TZ).astimezone(timezone.utc)
        except (ValueError, KeyError):
            scheduled_at = None

    teams: list[MatchTeamRef] = []
    for a in soup.select(".match-header-link"):
        img = a.select_one("img")
        teams.append(
            MatchTeamRef(
                vlr_id=_id_from(r"/team/(\d+)", a.get("href")),
                name=_text(a.select_one(".wf-title-med")),
                logo_url=image_url(img.get("src") if img else None),
            )
        )

    event = None
    ev = soup.select_one("a.match-header-event")
    if ev is not None:
        ev_id = _id_from(r"/event/(\d+)", ev.get("href"))
        series_el = ev.select_one(".match-header-event-series")
        name_el = ev.select_one("div > div")
        img = ev.select_one("img")
        if ev_id:
            event = EventRef(
                vlr_id=ev_id,
                name=_text(name_el),
                stage=_text(series_el) or None,
                logo_url=image_url(img.get("src") if img else None),
                url=f"{BASE_URL}/event/{ev_id}",
            )

    if scheduled_at is None and not teams:
        raise ParseError(f"경기 페이지 구조를 인식하지 못했습니다 (match {vlr_id})")

    return MatchDetail(
        vlr_id=vlr_id,
        scheduled_at=scheduled_at,
        team1=teams[0] if len(teams) > 0 else None,
        team2=teams[1] if len(teams) > 1 else None,
        event=event,
    )


# ---------------------------------------------------------------------------
# 경기 상세 (맵별 점수 + 선수 스탯)
# ---------------------------------------------------------------------------
# 확인한 구조 (2026-10)
#   .match-header-vs-note          'live' / 'final' / 'Bo3' ...
#   .vm-stats-gamesnav-item        data-game-id, 텍스트 '1 Lotus', mod-live / mod-disabled(미진행)
#   .vm-stats-game[data-game-id]   맵별 블록 ('all' = 전체 합산)
#     .vm-stats-game-header .score (mod-win), .map-name (+ span.picked mod-1|mod-2), .map-duration
#     .ovw-table (팀당 1개) > .ovw-row (mod-head 제외 = 선수)
#       .ovw-player-name, a[href=/player/{id}], .flag, .mod-agents img[title]
#       [data-col=rating2|acs|kd-diff|kast|adr|hsp|fb|fd] .side.mod-both
#       .ovw-kda-stat[data-col=kills|deaths|assists] .side.mod-both


@dataclass
class PlayerStatLine:
    name: str
    vlr_id: int | None
    country_code: str | None
    agents: list[str]
    rating: str | None
    acs: str | None
    kills: str | None
    deaths: str | None
    assists: str | None
    kd_diff: str | None
    kast: str | None
    adr: str | None
    hs: str | None
    fk: str | None
    fd: str | None


@dataclass
class MapResult:
    game_id: str
    order: int
    name: str
    status: str                   # live / done / upcoming
    team1_score: int | None
    team2_score: int | None
    picked_by: int | None         # 1 / 2 / None(디사이더)
    duration: str | None


@dataclass
class MatchFull:
    vlr_id: int
    status: str                   # live / completed / upcoming
    team1_score: int | None
    team2_score: int | None
    best_of: str | None
    detail: MatchDetail
    maps: list[MapResult] = field(default_factory=list)
    # game_id('all' 포함) → [팀1 선수들, 팀2 선수들]
    stats: dict[str, list[list[PlayerStatLine]]] = field(default_factory=dict)


def _side_value(cell: Tag | None) -> str | None:
    if cell is None:
        return None
    both = cell.select_one(".side.mod-both")
    value = _text(both if both is not None else cell).replace("\xa0", "").strip()
    return value or None


def _parse_ovw_table(table: Tag) -> list[PlayerStatLine]:
    players: list[PlayerStatLine] = []
    for row in table.select(".ovw-row"):
        if "mod-head" in row.get("class", []):
            continue
        name_el = row.select_one(".ovw-player-name")
        if name_el is None:
            continue
        link = row.select_one(".ovw-player a")

        def col(name: str) -> str | None:
            return _side_value(row.select_one(f'[data-col="{name}"]'))

        players.append(
            PlayerStatLine(
                name=_text(name_el),
                vlr_id=_id_from(r"/player/(\d+)", link.get("href") if link else None),
                country_code=_flag_code(row.select_one(".ovw-player")),
                agents=[img.get("title") or img.get("alt") or "" for img in row.select(".mod-agents img")],
                rating=col("rating2") or col("rating"),
                acs=col("acs"),
                kills=col("kills"),
                deaths=col("deaths"),
                assists=col("assists"),
                kd_diff=col("kd-diff"),
                kast=col("kast"),
                adr=col("adr"),
                hs=col("hsp"),
                fk=col("fb"),
                fd=col("fd"),
            )
        )
    return players


def _parse_legacy_table(table: Tag) -> list[PlayerStatLine]:
    """예전 경기 페이지 형식(table.wf-table-inset) 대비용."""
    players: list[PlayerStatLine] = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        name_el = row.select_one(".mod-player .text-of")
        if name_el is None or len(cells) < 13:
            continue
        vals = [_side_value(c) for c in cells]
        link = row.select_one(".mod-player a")
        players.append(
            PlayerStatLine(
                name=_text(name_el),
                vlr_id=_id_from(r"/player/(\d+)", link.get("href") if link else None),
                country_code=_flag_code(row.select_one(".mod-player")),
                agents=[img.get("title") or img.get("alt") or "" for img in cells[1].select("img")],
                rating=vals[2], acs=vals[3], kills=vals[4], deaths=vals[5], assists=vals[6],
                kd_diff=vals[7], kast=vals[8], adr=vals[9], hs=vals[10], fk=vals[11], fd=vals[12],
            )
        )
    return players


def parse_match_full(html: str, vlr_id: int) -> MatchFull:
    soup = _soup(html)
    detail = parse_match_page(html, vlr_id)

    # --- 경기 상태 / 세트 스코어 ---
    notes = [_text(n).lower() for n in soup.select(".match-header-vs-note")]
    if any(n == "live" for n in notes):
        status = "live"
    elif any(n == "final" for n in notes):
        status = "completed"
    else:
        status = "upcoming"
    best_of = next((n.upper() for n in notes if n.startswith("bo")), None)
    score_spans = [s for s in soup.select(".match-header-vs-score .sp-hide span") if "colon" not in " ".join(s.get("class", []))]
    s1 = _int_or_none(_text(score_spans[0])) if len(score_spans) >= 2 else None
    s2 = _int_or_none(_text(score_spans[1])) if len(score_spans) >= 2 else None

    # --- 맵 목록 (순서·진행 여부는 상단 탭에서) ---
    nav: dict[str, tuple[int, str, str]] = {}  # game_id → (순서, 이름, 상태)
    for item in soup.select(".vm-stats-gamesnav-item"):
        gid = item.get("data-game-id")
        if not gid or gid == "all":
            continue
        classes = item.get("class", [])
        m = re.match(r"(\d+)\s*(.*)", _text(item))
        order, name = (int(m.group(1)), m.group(2)) if m else (len(nav) + 1, _text(item))
        if "mod-live" in classes:
            map_status = "live"
        elif "mod-disabled" in classes or item.get("data-disabled") == "1":
            map_status = "upcoming"
        else:
            map_status = "done"
        nav[gid] = (order, name, map_status)

    maps: list[MapResult] = []
    stats: dict[str, list[list[PlayerStatLine]]] = {}
    for game in soup.select(".vm-stats-game"):
        gid = game.get("data-game-id")
        if not gid:
            continue

        tables = game.select(".ovw-table")
        teams_stats = [_parse_ovw_table(t) for t in tables[:2]]
        if not tables:
            teams_stats = [_parse_legacy_table(t) for t in game.select("table.wf-table-inset")[:2]]
        if len(teams_stats) == 2 and (teams_stats[0] or teams_stats[1]):
            stats[gid] = teams_stats

        if gid == "all":
            continue
        header = game.select_one(".vm-stats-game-header")
        scores = [_int_or_none(_text(s)) for s in header.select(".score")] if header else []
        name_el = game.select_one(".map-name span") or game.select_one(".map-name")
        picked = game.select_one(".map-name .picked")
        picked_by = None
        if picked is not None:
            picked_by = 1 if "mod-1" in picked.get("class", []) else 2 if "mod-2" in picked.get("class", []) else None
        order, nav_name, map_status = nav.get(gid, (len(maps) + 1, "", "done"))
        if map_status == "done" and scores[:2] == [0, 0] and not stats.get(gid):
            map_status = "upcoming"
        maps.append(
            MapResult(
                game_id=gid,
                order=order,
                name=_own_text(name_el) or nav_name or "?",
                status=map_status,
                team1_score=scores[0] if len(scores) >= 2 else None,
                team2_score=scores[1] if len(scores) >= 2 else None,
                picked_by=picked_by,
                duration=_text(game.select_one(".map-duration")) or None,
            )
        )
    # 탭에만 있고 블록이 없는 미진행 맵 (예: 2:0으로 끝나서 안 한 3세트)
    known = {m.game_id for m in maps}
    for gid, (order, name, map_status) in nav.items():
        if gid not in known:
            maps.append(MapResult(gid, order, name, "upcoming", None, None, None, None))
    maps.sort(key=lambda m: m.order)

    return MatchFull(
        vlr_id=vlr_id, status=status, team1_score=s1, team2_score=s2,
        best_of=best_of, detail=detail, maps=maps, stats=stats,
    )


# ---------------------------------------------------------------------------
# 팀 랭킹 (/rankings/{region})  — 선택자: .rank-item > .rank-item-rank-num, a.rank-item-team,
# .rank-item-team-country, .rank-item-rating(첫 번째 = 점수), .rank-item-streak(data-sort-value 부호 = 연승/연패)
# ---------------------------------------------------------------------------


@dataclass
class RankingEntry:
    rank: int
    vlr_id: int
    name: str
    country: str | None
    rating: int | None
    streak: int | None  # +N 연승, -N 연패
    logo_url: str | None


def parse_rankings(html: str) -> list[RankingEntry]:
    entries: list[RankingEntry] = []
    for item in _soup(html).select(".rank-item"):
        link = item.select_one("a.rank-item-team")
        vlr_id = _id_from(r"/team/(\d+)", link.get("href") if link else None)
        rank = _int_or_none(_text(item.select_one(".rank-item-rank-num")))
        if link is None or vlr_id is None or rank is None:
            continue
        name = _own_text(link.select_one(".ge-text")) or str(link.get("data-sort-value") or "")
        rating_el = item.select_one(".rank-item-rating")
        streak_el = item.select_one(".rank-item-streak")
        streak = None
        if streak_el is not None:
            try:
                streak = int(float(str(streak_el.get("data-sort-value"))))
            except (TypeError, ValueError):
                streak = None
        img = link.find("img")
        entries.append(RankingEntry(
            rank=rank, vlr_id=vlr_id, name=name,
            country=_text(item.select_one(".rank-item-team-country")) or None,
            rating=_int_or_none(_text(rating_el).split(" ")[0]) if rating_el else None,
            streak=streak,
            logo_url=image_url(img.get("src")) if img is not None else None,
        ))
    if not entries:
        raise ParseError("랭킹 표를 찾지 못했습니다 (페이지 구조가 바뀌었을 수 있음)")
    return entries


# ---------------------------------------------------------------------------
# 스크래퍼 (네트워크 + 시간대 보정)
# ---------------------------------------------------------------------------


class VlrScraper:
    OFFSET_TTL = 6 * 3600  # 목록 시간대 오프셋 재측정 주기

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or http_client
        self._offset: timedelta | None = None
        self._offset_at: float = 0.0

    async def _get(self, path: str) -> str:
        return await self.client.get_text(BASE_URL + path)

    # -- 기본 요청 -----------------------------------------------------------

    async def search_teams(self, query: str) -> list[TeamSearchResult]:
        html = await self._get(f"/search/?q={quote(query)}&type=teams")
        return parse_search_teams(html)

    async def fetch_team(self, vlr_id: int) -> TeamPage:
        html = await self._get(f"/team/{vlr_id}")
        page = await asyncio.to_thread(parse_team_page, html, vlr_id)
        await self._apply_offset(page.upcoming + page.recent)
        return page

    async def fetch_match(self, vlr_id: int) -> MatchDetail:
        return parse_match_page(await self._get(f"/{vlr_id}"), vlr_id)

    async def fetch_match_full(self, vlr_id: int) -> MatchFull:
        html = await self._get(f"/{vlr_id}")
        # 경기 페이지는 400KB 정도라 파싱에 시간이 걸린다 → 별도 스레드에서 (봇이 멈추지 않게)
        return await asyncio.to_thread(parse_match_full, html, vlr_id)

    async def fetch_rankings(self, region: str) -> list[RankingEntry]:
        path = "/rankings" if region == "world" else f"/rankings/{region}"
        return await asyncio.to_thread(parse_rankings, await self._get(path))

    async def fetch_upcoming_matches(self) -> list[MatchListItem]:
        items = parse_matches_list(await self._get("/matches"))
        await self._apply_offset(items)
        return items

    async def fetch_results(self, page: int = 1) -> list[MatchListItem]:
        path = "/matches/results" if page == 1 else f"/matches/results/?page={page}"
        items = parse_matches_list(await self._get(path))
        await self._apply_offset(items)
        return items

    # -- 시간대 보정 ---------------------------------------------------------

    async def _apply_offset(self, items: list[MatchListItem] | list[TeamMatchItem]) -> None:
        offset = await self._get_offset(items)
        for item in items:
            if item.local_dt is not None and offset is not None:
                item.scheduled_at = (item.local_dt - offset).replace(tzinfo=timezone.utc)

    async def _get_offset(self, items: list[MatchListItem] | list[TeamMatchItem]) -> timedelta | None:
        if self._offset is not None and time.monotonic() - self._offset_at < self.OFFSET_TTL:
            return self._offset
        sample = next((i for i in items if i.local_dt is not None), None)
        if sample is None:
            return self._offset
        try:
            detail = await self.fetch_match(sample.vlr_id)
        except Exception as exc:
            log.warning("시간대 보정 실패 (match %s): %s", sample.vlr_id, exc)
            return self._offset
        if detail.scheduled_at is None:
            return self._offset

        raw = sample.local_dt - detail.scheduled_at.replace(tzinfo=None)
        minutes = round(raw.total_seconds() / 60 / 15) * 15  # 15분 단위로 반올림
        if abs(minutes) > 14 * 60:
            log.warning("시간대 보정값이 비정상입니다 (%s분) → 무시", minutes)
            return self._offset
        self._offset = timedelta(minutes=minutes)
        self._offset_at = time.monotonic()
        log.info("VLR 목록 시간대 보정: UTC%+.2g시간", minutes / 60)
        return self._offset


vlr = VlrScraper()
