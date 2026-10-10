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
# 등급별 일반 상점 가격 (VP, 총기 기준). 공개 API에는 가격이 없어서 등급으로 추정한다 — 근접 무기·특별 판매는 다를 수 있다.
TIER_PRICE = {
    "12683d76-48d7-84a3-4e09-6985794f0445": 875,    # 셀렉트
    "0cebb8be-46d7-c12a-d306-e9907bfc5a25": 1275,   # 딜럭스
    "60bca009-4182-7998-dee7-b8a2558dc369": 1775,   # 프리미엄
    "411e4a55-4e59-7757-41f0-86a53f101bb5": 2175,   # 얼티밋
    "e046854e-406c-37f4-6607-19a9ba8426fc": 2475,   # 익스클루시브
}
# 세트 목록에서 뺄 것: 역습 세트, VCT 클래식·팀 캡슐, 자선 세트
EXCLUDED_BUNDLE = re.compile(r"역습|캡슐|자선|vct|charity|capsule|counter\s*/?\s*attack", re.I)
Variant = tuple  # (색상 이름, 이미지 URL, 영상 URL)


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
    variants: list[tuple] = field(default_factory=list)   # (색상 이름, 이미지, 영상) — 첫 번째가 기본
    tier_icon: str | None = None
    price: int | None = None        # 등급 기준 가격 (VP). 근접 무기·등급 없음은 None
    melee: bool = False
    label: str = ""          # 목록·선택 메뉴에 보일 이름 (이름이 같은 스킨끼리는 구분 글자가 붙음)


@dataclass
class Bundle:
    uuid: str
    name: str
    subtext: str | None
    description: str | None
    icon: str | None
    skins: list[Skin] = field(default_factory=list)
    label: str = ""                 # 이름이 같은 세트끼리 구분되는 이름 (예: 'RGX 11z 프로 (2.0)')
    asset_path: str | None = None
    version: str | None = None


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


def _version(text: str) -> str | None:
    """글 안에서 '2.0', '3.0' 같은 버전 표기를 찾는다."""
    m = re.search(r"(?<![\d.])(\d)\.0(?![\d.])", text)
    return f"{m.group(1)}.0" if m else None


def _chroma_label(chroma_name: str, skin_name: str) -> str:
    """색상 변형 이름에서 스킨 이름 부분을 빼고 색 이름만 남긴다 ('리버 밴달 (보라색)' → '보라색')."""
    m = re.search(r"\(([^)]+)\)\s*$", chroma_name)
    if m:
        return m.group(1)
    return chroma_name.replace(skin_name, "").strip() or chroma_name


def _disambiguate(skins: list[Skin]) -> None:
    """이름이 같은 스킨(예: 원본과 2.0 버전)에 컬렉션 → 무기 → 등급 순으로 서로 다른 값을 붙여 구분한다."""
    groups: dict[str, list[Skin]] = {}
    for s in skins:
        s.label = s.name
        groups.setdefault(key(s.name), []).append(s)
    for g in groups.values():
        if len(g) < 2:
            continue
        for attr in ("theme", "weapon", "tier"):
            vals = [getattr(s, attr) for s in g]
            if all(vals) and len(set(vals)) == len(g):
                for s, v in zip(g, vals):
                    s.label = f"{s.name} ({v})"
                break
        else:
            for i, s in enumerate(g, 1):
                s.label = f"{s.name} ({i})"


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
            melee = "Melee" in str(w.get("category") or "")
            skin_video = next((lv.get("streamedVideo") for lv in reversed(levels) if lv.get("streamedVideo")), None)

            # 색상 변형: 이름이 스킨 이름과 같은 항목은 '기본' 색이므로 따로 세지 않고 기본 하나로 합친다
            base_img, base_video = icon, skin_video
            extras: list[tuple] = []
            for c in s.get("chromas") or []:
                img = c.get("fullRender") or c.get("displayIcon")
                if not img:
                    continue
                cname = (c.get("displayName") or "").strip()
                if cname == name.strip():
                    base_img = img
                    base_video = c.get("streamedVideo") or base_video
                elif img != base_img and all(img != e[1] for e in extras):
                    extras.append((_chroma_label(cname, name), img, c.get("streamedVideo") or skin_video))
            variants = [("기본", base_img, base_video)] + extras
            price = None if melee else TIER_PRICE.get(s.get("contentTierUuid"))
            skins.append(Skin(s["uuid"], name, w.get("displayName") or "", tier.get("displayName"),
                              _color(tier.get("highlightColor")), base_img, theme_name.get(s.get("themeUuid")),
                              len(extras), len(levels), variants, tier.get("displayIcon"), price, melee))

    _disambiguate(skins)
    by_theme: dict[str, list[Skin]] = {}
    for sk in skins:
        if sk.theme:
            by_theme.setdefault(key(_BUNDLE_SUFFIX.sub("", sk.theme)), []).append(sk)

    out: list[Bundle] = []
    versions: dict[str, str | None] = {}
    for b in bundles:
        name = b.get("displayName") or ""
        if not name or EXCLUDED_BUNDLE.search(f"{name} {b.get('displayNameSubText') or ''}"):
            continue
        bk = key(_BUNDLE_SUFFIX.sub("", name))
        # 이름이 같아도 2.0·3.0 판은 이름·부제·설명·에셋 경로 어딘가에 버전이 적혀 있으면 그걸로 컬렉션을 찾는다
        ver = _version(" ".join(str(b.get(k) or "") for k in
                                ("displayName", "displayNameSubText", "extraDescription", "description", "assetPath")))
        members = (by_theme.get(bk + ver.replace(".", ""), []) if ver else []) or (by_theme.get(bk, []) if bk else [])
        bundle = Bundle(b["uuid"], name, b.get("displayNameSubText"), b.get("extraDescription") or b.get("description"),
                        b.get("displayIcon") or b.get("displayIcon2") or b.get("verticalPromoImage"), members, name,
                        b.get("assetPath"), ver)
        versions[bundle.uuid] = ver
        if members:                 # 스킨이 없는 세트(분무기·카드만 있는 묶음 등)는 뺀다
            out.append(bundle)

    # 이름이 같은 세트(2.0·3.0 판 등)는 하나만 남긴다: 스킨이 가장 많은 것 → 버전 표기가 없는 원본 → 먼저 나온 것
    best: dict[str, Bundle] = {}
    for b in out:
        k = key(b.name)
        cur = best.get(k)
        if cur is None or (len(b.skins), b.version is None) > (len(cur.skins), cur.version is None):
            best[k] = b
    out = [b for b in out if best[key(b.name)] is b]
    return Catalog(skins, out)


def price_text(s: Skin) -> str | None:
    return f"{s.price:,} VP" if s.price else None


def trailer_url(bundle_name: str) -> str:
    """한국 공식 트레일러를 찾는 유튜브 검색 링크 (번들마다 트레일러 주소를 알려 주는 공개 데이터가 없다)."""
    from urllib.parse import quote_plus

    return "https://www.youtube.com/results?search_query=" + quote_plus(f"발로란트 코리아 {bundle_name} 트레일러")


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
    starts = [b for b in cat.bundles if key(b.label or b.name).startswith(q)]
    contains = [b for b in cat.bundles if q in key(b.label or b.name) and b not in starts]
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
