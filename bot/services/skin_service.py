"""스킨·번들 정보 (valorant-api.com 공개 데이터). 로그인이 필요 없는 정보만 다룬다.

- 스킨/티어/테마/번들 목록은 거의 안 바뀌므로 한 번 받아서 6시간 메모리에 둔다 (요청 4번).
- 번들 → 스킨 연결: 번들 이름과 같은 이름의 테마(컬렉션)에 속한 스킨을 그 번들의 구성으로 본다.
  이름이 안 맞는 번들은 구성 없이 이미지·설명만 보여준다.
- 파싱 함수는 네트워크 없이 테스트할 수 있게 분리했다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger("valobot.service.skin")

API = "https://valorant-api.com/v1"
LANG = "ko-KR"
TTL = 6 * 3600
STANDARD_THEME = "5a629df4-4765-0214-bd40-fbb96542941f"   # 기본 스킨 묶음 (목록에서 제외)
_RANDOM = re.compile(r"random|무작위", re.I)
_BUNDLE_SUFFIX = re.compile(r"\s*(컬렉션|번들|세트|collection|bundle|set)\s*$", re.I)


@dataclass
class Skin:
    uuid: str
    name: str
    weapon: str
    tier: str | None
    color: int | None
    icon: str | None
    theme: str | None
    chromas: int
    levels: int
    variants: list[tuple[str, str | None]] = field(default_factory=list)   # (색상 이름, 이미지) — 첫 번째가 기본


@dataclass
class Bundle:
    uuid: str
    name: str
    subtext: str | None
    description: str | None
    icon: str | None
    skins: list[Skin] = field(default_factory=list)


@dataclass
class Catalog:
    skins: list[Skin]
    bundles: list[Bundle]
    loaded_at: float = 0.0


def key(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())


def _color(hexstr: str | None) -> int | None:
    try:
        return int((hexstr or "")[:6], 16)
    except ValueError:
        return None


def _chroma_label(chroma_name: str, skin_name: str) -> str:
    """색상 변형 이름에서 스킨 이름 부분을 빼고 색 이름만 남긴다 ('리버 밴달 (보라색)' → '보라색')."""
    m = re.search(r"\(([^)]+)\)\s*$", chroma_name)
    if m:
        return m.group(1)
    return chroma_name.replace(skin_name, "").strip() or chroma_name


def parse_catalog(weapons: list[dict], tiers: list[dict], themes: list[dict], bundles: list[dict]) -> Catalog:
    tier_by = {t.get("uuid"): t for t in tiers}
    theme_name = {t.get("uuid"): t.get("displayName") for t in themes}
    skins: list[Skin] = []
    for w in weapons:
        for s in w.get("skins") or []:
            name = s.get("displayName") or ""
            if not name or s.get("themeUuid") == STANDARD_THEME or _RANDOM.search(name):
                continue
            levels = s.get("levels") or []
            icon = s.get("displayIcon") or (levels[0].get("displayIcon") if levels else None) \
                or next((c.get("fullRender") for c in (s.get("chromas") or []) if c.get("fullRender")), None)
            tier = tier_by.get(s.get("contentTierUuid")) or {}
            variants = [("기본", icon)]
            for c in s.get("chromas") or []:
                img = c.get("fullRender") or c.get("displayIcon")
                if img and img != icon:
                    variants.append((_chroma_label(c.get("displayName") or "", name), img))
            skins.append(Skin(s["uuid"], name, w.get("displayName") or "", tier.get("displayName"),
                              _color(tier.get("highlightColor")), icon, theme_name.get(s.get("themeUuid")),
                              len(s.get("chromas") or []), len(levels), variants))

    by_theme: dict[str, list[Skin]] = {}
    for sk in skins:
        if sk.theme:
            by_theme.setdefault(key(_BUNDLE_SUFFIX.sub("", sk.theme)), []).append(sk)

    out: list[Bundle] = []
    for b in bundles:
        name = b.get("displayName") or ""
        if not name:
            continue
        bk = key(_BUNDLE_SUFFIX.sub("", name))
        members = by_theme.get(bk, []) if bk else []
        out.append(Bundle(b["uuid"], name, b.get("displayNameSubText"), b.get("extraDescription") or b.get("description"),
                          b.get("displayIcon") or b.get("displayIcon2") or b.get("verticalPromoImage"), members))
    return Catalog(skins, out)


def search_skins(cat: Catalog, query: str, limit: int = 25) -> list[Skin]:
    """띄어쓰기로 나눈 낱말이 모두 (무기·이름·컬렉션) 안에 들어 있는 스킨. 이름이 짧고 앞부분이 맞을수록 위."""
    tokens = [key(t) for t in query.split() if key(t)]
    if not tokens:
        return cat.skins[:limit]
    scored = []
    for s in cat.skins:
        hay = key(f"{s.name} {s.weapon} {s.theme or ''}")
        if all(t in hay for t in tokens):
            scored.append((0 if key(s.name).startswith(tokens[0]) else 1, len(s.name), s))
    scored.sort(key=lambda r: r[:2])
    return [r[2] for r in scored[:limit]]


def search_bundles(cat: Catalog, query: str, limit: int = 25) -> list[Bundle]:
    q = key(query)
    if not q:
        return cat.bundles[:limit]
    starts = [b for b in cat.bundles if key(b.name).startswith(q)]
    contains = [b for b in cat.bundles if q in key(b.name) and b not in starts]
    return (starts + contains)[:limit]


# ---------------------------------------------------------------------------
# 불러오기 (캐시)
# ---------------------------------------------------------------------------

_catalog: Catalog | None = None
_lock = asyncio.Lock()
_task: asyncio.Task | None = None


async def _get_json(session, path: str) -> list[dict]:
    async with session.get(f"{API}/{path}{'&' if '?' in path else '?'}language={LANG}") as resp:
        resp.raise_for_status()
        return (await resp.json()).get("data") or []


async def load(force: bool = False) -> Catalog:
    global _catalog
    async with _lock:
        if _catalog and not force and time.monotonic() - _catalog.loaded_at < TTL:
            return _catalog
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "ValoProBot/0.3"}) as session:
            weapons, tiers, themes, bundles = await asyncio.gather(
                _get_json(session, "weapons"), _get_json(session, "contenttiers"),
                _get_json(session, "themes"), _get_json(session, "bundles"))
        cat = parse_catalog(weapons, tiers, themes, bundles)
        cat.loaded_at = time.monotonic()
        _catalog = cat
        log.info("스킨 목록 불러옴: 스킨 %d · 번들 %d", len(cat.skins), len(cat.bundles))
        return cat


def cached() -> Catalog | None:
    """이미 불러온 목록 (없으면 None). 자동완성처럼 기다릴 수 없는 곳에서 쓴다 — 없으면 뒤에서 불러오기 시작."""
    global _task
    stale = _catalog is None or time.monotonic() - _catalog.loaded_at >= TTL
    if stale and (_task is None or _task.done()):
        async def run() -> None:
            try:
                await load()
            except Exception as exc:
                log.warning("스킨 목록 불러오기 실패: %s: %s", type(exc).__name__, exc)

        try:
            _task = asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            pass
    return _catalog
