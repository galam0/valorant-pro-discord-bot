"""ProSettings.net 스크래퍼 (VALORANT 선수 설정).

확인한 구조 (2026-10, https://prosettings.net/players/stax/)
- robots.txt: /?s=, /search/(검색), /wp-json/(API) 금지 → 사용하지 않음. /players/{slug}/ 는 허용.
- slug = 닉네임 소문자 (stax, t3xture, buzz, izu ...)
- section.intro
    h1 = 닉네임, .last_updated time[datetime] = 마지막 업데이트
    table.data tr.field-name / field-country(img flags/…/kr.svg) / field-team(a)
    img[class*=220x220] = 선수 사진
- section.settings-group.section--mouse      tr[data-field=dpi|sensitivity|zoom_sensitivity|edpi|hz|windows_sensitivity]
- section.settings-group.section--crosshair  tr[data-field=color|crosshair_color|outlines|center_dot|...|code]
- section.settings-group.section--video_settings  tr[data-field=resolution|aspect_ratio|...]
- .cta-box  h4 a = 제품명, .cta-box__tag = 분류(Mouse, Keyboard, Mousepad, Monitor, Headset ...)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from bot.scrapers.http import HttpClient, ScrapeError, http_client

log = logging.getLogger("valobot.scraper.prosettings")

BASE_URL = "https://prosettings.net"


class NotValorantPlayer(Exception):
    """페이지는 있지만 VALORANT 선수가 아님 (다른 게임 선수와 slug가 같을 때)."""


class PlayerPageNotFound(Exception):
    pass


@dataclass
class ProPlayer:
    slug: str
    url: str
    nickname: str
    real_name: str | None
    country_name: str | None
    country_code: str | None
    team_name: str | None
    photo_url: str | None
    last_updated: datetime | None
    mouse: dict[str, str] = field(default_factory=dict)      # dpi, sensitivity, zoom_sensitivity, edpi, hz ...
    crosshair: dict[str, str] = field(default_factory=dict)  # color, crosshair_color, outlines, ... code
    crosshair_inner: dict[str, str] = field(default_factory=dict)
    crosshair_outer: dict[str, str] = field(default_factory=dict)
    video: dict[str, str] = field(default_factory=dict)
    gear: list[tuple[str, str, str | None]] = field(default_factory=list)  # (분류, 제품명, 링크)


def _text(el: Tag | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _fields(scope: Tag | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if scope is None:
        return out
    for tr in scope.select("tr[data-field]"):
        key = (tr.get("data-field") or "").strip()
        value = _text(tr.find("td"))
        if key and key not in out and value and value.lower() != "unknown":
            out[key] = value
    return out


def _crosshair_part(section: Tag | None, part: str) -> dict[str, str]:
    """크로스헤어 하위 블록(section.section--inner_lines / --outer_lines) 값.
    movement_error 같은 키가 안쪽·바깥쪽에 모두 있어서 블록별로 따로 읽는다."""
    if section is None:
        return {}
    return _fields(section.select_one(f"section.section--{part}"))


def parse_player_page(html: str, slug: str) -> ProPlayer:
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.find("title"))
    intro = soup.select_one("section.intro")
    if intro is None:
        raise ScrapeError(f"ProSettings 선수 페이지 구조를 인식하지 못했습니다 ({slug})")
    if "valorant" not in title.lower() and soup.select_one(".section--crosshair") is None:
        raise NotValorantPlayer(slug)

    nickname = _text(intro.select_one("h1")) or slug
    updated = None
    time_el = intro.select_one(".last_updated time[datetime]")
    if time_el is not None:
        try:
            updated = datetime.fromisoformat(time_el["datetime"]).astimezone(timezone.utc)
        except (ValueError, KeyError):
            updated = None

    country_td = intro.select_one("tr.field-country td")
    country_code = None
    flag = country_td.select_one("img") if country_td else None
    if flag is not None:
        m = re.search(r"/([a-z]{2})\.svg", flag.get("src") or "")
        country_code = m.group(1) if m else None

    team_td = intro.select_one("tr.field-team td")
    photo = (intro.parent or intro).select_one('img[class*="220x220"]')

    crosshair_section = soup.select_one("section.section--crosshair")
    gear: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for box in soup.select(".cta-box"):
        tag = _text(box.select_one(".cta-box__tag"))
        name_a = box.select_one("h4 a") or box.select_one("h4")
        name = _text(name_a)
        if not tag or not name or tag in seen:
            continue
        seen.add(tag)
        href = name_a.get("href") if name_a is not None and name_a.name == "a" else None
        gear.append((tag, name, href))

    return ProPlayer(
        slug=slug,
        url=f"{BASE_URL}/players/{slug}/",
        nickname=nickname,
        real_name=_text(intro.select_one("tr.field-name td")) or None,
        country_name=_text(country_td) or None,
        country_code=country_code,
        team_name=_text(team_td.select_one("a") if team_td else None) or _text(team_td) or None,
        photo_url=photo.get("src") if photo is not None else None,
        last_updated=updated,
        mouse=_fields(soup.select_one("section.section--mouse")),
        crosshair=_fields(crosshair_section.select_one("section.section--primary") if crosshair_section else None)
        | _fields(crosshair_section.select_one("section.section--profile") if crosshair_section else None),
        crosshair_inner=_crosshair_part(crosshair_section, "inner_lines"),
        crosshair_outer=_crosshair_part(crosshair_section, "outer_lines"),
        video=_fields(soup.select_one("section.section--video_settings")),
        gear=gear,
    )


def slug_candidates(nickname: str) -> list[str]:
    """닉네임 → ProSettings slug 후보. 대부분 소문자 닉네임 그대로다."""
    base = nickname.strip().lower()
    simple = re.sub(r"[^0-9a-z]+", "-", base).strip("-")
    out = [s for s in (simple, base.replace(" ", "-")) if s]
    return list(dict.fromkeys(out))


class ProSettingsScraper:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or http_client

    async def fetch_player(self, slug: str) -> ProPlayer:
        url = f"{BASE_URL}/players/{slug}/"
        try:
            html = await self.client.get_text(url)
        except ScrapeError as exc:
            if exc.status == 404:
                raise PlayerPageNotFound(slug) from exc
            raise
        # 선수 페이지는 250KB 정도 → 파싱은 별도 스레드에서
        return await asyncio.to_thread(parse_player_page, html, slug)

    async def find_player(self, nickname: str) -> ProPlayer:
        """slug 후보를 차례로 시도. 모두 없으면 PlayerPageNotFound."""
        last: Exception | None = None
        for slug in slug_candidates(nickname):
            try:
                return await self.fetch_player(slug)
            except (PlayerPageNotFound, NotValorantPlayer) as exc:
                last = exc
        raise PlayerPageNotFound(nickname) from last


prosettings = ProSettingsScraper()
