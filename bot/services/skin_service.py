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
# 공개 API에는 가격이 없다. 총기는 등급마다 상점 가격이 정해져 있어 등급으로 정한다
# (셀렉트 875 · 딜럭스 1275 · 프리미엄 1775 · 얼티밋 2475 · 익스클루시브는 세트마다 달라 보통 2175 → '약').
SELECT, DELUXE, PREMIUM, ULTRA, EXCLUSIVE = (
    "12683d76-48d7-84a3-4e09-6985794f0445", "0cebb8be-46d7-c12a-d306-e9907bfc5a25",
    "60bca009-4182-7998-dee7-b8a2558dc369", "411e4a55-4e59-7757-41f0-86a53f101bb5",
    "e046854e-406c-37f4-6607-19a9ba8426fc")
TIER_PRICE = {SELECT: 875, DELUXE: 1275, PREMIUM: 1775, ULTRA: 2475, EXCLUSIVE: 2175}
APPROX_TIERS = {EXCLUSIVE}
# 근접 무기는 등급이 같아도 값이 제각각이라 스킨별 실제 상점 가격을 쓴다 (영어 이름 기준).
# 여기에 없는 (새로 나온) 근접 무기는 등급으로 어림한다 → '약'.
MELEE_TIER_PRICE = {SELECT: 1750, DELUXE: 2550, PREMIUM: 3550, ULTRA: 4950, EXCLUSIVE: 4350}
MELEE_PRICE_EN = {   # 출처: THESPIKE.GG 근접 무기 가격 목록 (2026), GINX·Dot Esports·FPSNews 로 보충·확인
    1750: "Daydreams Crowbar; Fortune's Scepter; Intergrade Blade; Switchback Ascender; Smite Knife; Luxe Knife; Reverie Sword; Storm Maw Axe; Smite Hammer",
    2550: "Aperture Stiletto; Chromedek Gauntlet; Combat Crafts Axe; Emberclad Hammer; Kaimana; MK.VII Liberty Combat Knife; Orion Sword; Wonderstallion Hammer; No Limits Bat; Prism Knife; Hu Else; Snowfall Wand; Titanmail Mace; Blade of Serket; Caeruleus; Winterwunderland Candy Cane; Equilibrium; Catrina; Altitude Knuckle Knife; Wasteland Crowbar; Jellybeam Sugarslice; Nanomight Knuckles; SilkLeaf Fan; Hi-DR0 Baton; VALORANT GO! Vol. 3 Dagger",
    3550: "Spine Dagger; Ego Knife; Gravitational Uranium Neuroblaster; Yoru's Stylish Butterfly Knife; Gaia's Fury; Gravitational Uranium Neuroblaster Baton; Prime Axe; Sovereign Sword; Oni Claw; Nebula Knife; Spline Dagger; Reaver Knife; Ion Energy Sword; VALORANT GO! Vol. 1 Knife; Yoru's Stylish Butterfly Comb; Prime 2.0 Karambit; Celestial Fan; Forsaken Ritual Blade; Origin Crescent Blade; Neptune Anchor; Xenohunter Knife; Crimsonbeast Hammer; Soulstrife Scythe; Cryostasis Impact Drill; Luna's Descent; Radiant Crisis 001 Baseball Bat; Recon Balisong; Gaia's Wrath; Magepunk Electroblade; Magepunk Shock Gauntlet; Prosperity; Hack; Black.Market Butterfly Knife; Solarstride Flamethrower; Minima Karambit; Neptune Hook",
    3915: "5 Years // Beta Remastered Knife",
    4350: "Singularity Knife; Arcane Gauntlets; Blade of Aemondir; Blades of Primordia; Doombringer Battleaxe; Eternal Sovereign; Mystbloom Kunai; Overdrive Blade; Relic Stone Daggers; Ruyi Staff; Singularity Butterfly Knife; XERØFANG Knife; Blades of Imperium; Araxys Bio Harvester; Terminus a Quo; RGX 11z Pro Blade; RGX 11z Pro Firefly; Reaver Karambit; Ion Karambit; Broken Blade of the Ruined King; Relic of the Sentinel; Blade of Chaos; Neo Frontier Axe; Magepunk Sparkswitch; Mystbloom Fanblade; ORA by OneTap Knife; Dolmir's Judgement; Flail of Chaos; Bubblegum Deathwish Chainsaw; Divergence Staff; Bolt Knife; Helix Daggers; RGX 11z Pro Karambit; Blackthorn Blades; SplashX Gloves; Neo Frontier Lasso; Rogue Push Daggers; Holoflare",
    4550: "Glitchpop Dagger; Glitchpop Axe; BlastX Polymer KnifeTech Coated Knife",
    4710: "Ignite Fan",
    4950: "Evori's Spellcaster; Elderflame Dagger; Personal Administrative Melee Unit",
    5350: "VCT 2026 SIGIL; Araxys Bio-Atomizers; Champions 2024 Blade; EX.O Edge; Kuronami no Yaiba; Nocturnum Scythe; Waveform; Champions 2023 Kunai; Champions 2022 Butterfly Knife; Champions 2021 Karambit; Onimaru Kunitsuna; Reaver Butterfly Knife; Champions 2025 Butterfly Knife; Phaseguard Splitter; Cyrax Fanblade; Kuronami Naru-Kami; Champions 2026 Fan; Kogitsune; Blackspyre Divide; Suit of Aeris",
    5440: "VCT LOCK//IN Misericórdia",
    5850: "VCT Karambit; 2025 VCT Karambit; VCT 2025 Karambit",
    5950: "Power Fist",
}
# 익스클루시브 총기는 세트마다 값이 다르다 → 컬렉션(테마) 한국어 이름으로 실제 가격. 없으면 '약 2,175'.
# 출처: Dot Esports·PCGamesN·THESPIKE·win.gg 가격 목록 (2026)
EXCLUSIVE_GUN_PRICE = {
    2175: "둠브링어, 글리치팝, 돌미르의 복수, 네오 프런티어, 빛의 감시자, 블라스트X, 싱귤래러티, 미스트블룸, RGX 11z 프로, "
          "다이버전스, 아락시스, 크로노보이드, 혼돈의 서막, 임페리움, 프리모디움, 아케인 컬렉터 세트, 오버드라이브, 로그, "
          "검은 가시, 홀로 메리디안, 사이랙스, 녹터넘, 죽음의 풍선껌, 대몰락",
    2375: "쿠로나미, EX.O, 에리스, 스플래시X, 아야카시",
    2675: "2021 챔피언스, 2022 챔피언스, 2023 챔피언스, 2024 챔피언스, 2025 챔피언스, 2026 챔피언스, 스펙트럼",
}
EXCLUSIVE_GUN = {n: p for p, names in EXCLUSIVE_GUN_PRICE.items() for n in names.split(", ")}
_CAPSULE_THEME = re.compile(r"^VCT\d*\s*x\s", re.I)
MELEE_WEAPON = "2f59173c-4bed-b6c3-2191-dea9b58be9c7"


def _norm_en(name: str) -> str:
    return re.sub(r"[^0-9a-zø]", "", (name or "").lower())


MELEE_PRICE = {_norm_en(n): price for price, names in MELEE_PRICE_EN.items() for n in names.split("; ")}
# 세트 목록에서 뺄 것: 역습 세트, VCT 클래식·팀 캡슐, 자선 세트
# 제외 규칙에 걸려도 남길 것: 해마다 나오는 VCT 시즌 세트(칼 포함), VCT LOCK//IN
KEEP_BUNDLE = re.compile(r"^\s*(20\d\d\s*vct\s*시즌|vct\s*20\d\d\s*season|vct\s*lock\s*//\s*in)\s*$", re.I)
EXCLUDED_BUNDLE = re.compile(r"역습|캡슐|자선|vct.*(클래식|classic)|(클래식|classic).*vct|charity|capsule|counter\s*/?\s*attack", re.I)
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
    price: int | None = None        # 상점 가격 (VP). 등급 없음(배틀패스 등)은 None
    melee: bool = False
    label: str = ""          # 목록·선택 메뉴에 보일 이름 (이름이 같은 스킨끼리는 구분 글자가 붙음)
    reward: bool = False     # 배틀패스·이벤트 패스 보상 (상점 판매 아님)
    capsule: bool = False    # VCT 팀 캡슐 전용 (단품 판매 안 함)
    approx: bool = False     # 가격이 어림값인지 (익스클루시브 총기, 가격표에 없는 근접 무기)


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
    icons: list[str] = field(default_factory=list)   # 세트 그림 후보 (작은 것부터)


@dataclass
class Catalog:
    skins: list[Skin]
    bundles: list[Bundle]
    loaded_at: float = 0.0
    dropped: list[tuple[str, str]] = field(default_factory=list)   # (세트 이름, 빠진 이유) — 진단용


def key(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())


def _color(hexstr: str | None) -> int | None:
    try:
        return int((hexstr or "")[:6], 16)
    except ValueError:
        return None


def sort_key(name: str) -> tuple:
    """숫자 → 영어 → 가나다 순. 앞의 기호(//, [ 등)는 무시하고, 숫자는 크기대로(2 < 10) 비교한다."""
    s = re.sub(r"^[^0-9A-Za-z가-힣]+", "", name or "")
    first = s[:1]
    group = 0 if first.isdigit() else 1 if first.isascii() and first.isalpha() else 2 if first else 3
    parts = re.split(r"(\d+)", s.casefold())
    return (group, [int(x) if x.isdigit() else x for x in parts])


def _tokens(text: str) -> frozenset[str]:
    """낱말 집합 (순서 무시). 'Champions 2023' 과 '2023 Champions' 를 같게 본다."""
    return frozenset(re.findall(r"[0-9a-z가-힣]+", (text or "").lower()))


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


def parse_catalog(weapons: list[dict], tiers: list[dict], themes: list[dict], bundles: list[dict],
                  melee_en: dict[str, str] | None = None, reward_levels: set[str] | None = None) -> Catalog:
    """melee_en: 근접 무기 스킨 uuid → 영어 이름 (근접 무기 가격표를 찾는 데 씀).
    reward_levels: 배틀패스·이벤트 패스 보상으로 주는 스킨 레벨 uuid (상점에서 팔지 않으니 가격 없음)."""
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
            price, approx = skin_price(s.get("contentTierUuid"), melee, (melee_en or {}).get(s["uuid"]))
            if reward_levels and any(lv.get("uuid") in reward_levels for lv in levels):
                price, approx, reward = None, False, True      # 패스 보상 스킨
            else:
                reward = False
            skins.append(Skin(s["uuid"], name, w.get("displayName") or "", tier.get("displayName"),
                              _color(tier.get("highlightColor")), base_img, theme_name.get(s.get("themeUuid")),
                              len(extras), len(levels), variants, tier.get("displayIcon"), price, melee, approx=approx, reward=reward))

    # 공개 API는 근접 무기를 모두 '익스클루시브'로 준다 → 같은 컬렉션 총기 스킨의 등급을 따른다
    gun_tiers: dict[str, list[Skin]] = {}
    for sk in skins:
        if not sk.melee and sk.theme and sk.tier:
            gun_tiers.setdefault(sk.theme, []).append(sk)
    for sk in skins:
        guns = gun_tiers.get(sk.theme or "") if sk.melee else None
        if guns:
            count: dict[str | None, int] = {}
            for g in guns:
                count[g.tier] = count.get(g.tier, 0) + 1
            ref = max(guns, key=lambda g: count[g.tier])
            sk.tier, sk.color, sk.tier_icon = ref.tier, ref.color, ref.tier_icon

    for sk in skins:
        if sk.melee or sk.reward or not sk.approx:
            continue
        if _CAPSULE_THEME.search(sk.theme or ""):
            sk.price, sk.approx, sk.capsule = None, False, True      # 팀 캡슐 클래식: 단품 판매 없음
        elif (sk.theme or "") in EXCLUSIVE_GUN:
            sk.price, sk.approx = EXCLUSIVE_GUN[sk.theme], False

    _disambiguate(skins)
    by_theme: dict[str, list[Skin]] = {}
    for sk in skins:
        if sk.theme:
            by_theme.setdefault(key(_BUNDLE_SUFFIX.sub("", sk.theme)), []).append(sk)

    theme_tokens = [(_tokens(_BUNDLE_SUFFIX.sub("", th)), sks) for th, sks in
                    {sk.theme: [x for x in skins if x.theme == sk.theme] for sk in skins if sk.theme}.items()]
    dropped: list[tuple[str, str]] = []
    out: list[Bundle] = []
    versions: dict[str, str | None] = {}
    for b in bundles:
        name = b.get("displayName") or ""
        if not name:
            continue
        if not KEEP_BUNDLE.search(name) and EXCLUDED_BUNDLE.search(f"{name} {b.get('displayNameSubText') or ''}"):
            dropped.append((name, "제외 규칙"))
            continue
        bk = key(_BUNDLE_SUFFIX.sub("", name))
        # 이름이 같아도 2.0·3.0 판은 이름·부제·설명·에셋 경로 어딘가에 버전이 적혀 있으면 그걸로 컬렉션을 찾는다
        ver = _version(" ".join(str(b.get(k) or "") for k in
                                ("displayName", "displayNameSubText", "extraDescription", "description", "assetPath")))
        members = (by_theme.get(bk + ver.replace(".", ""), []) if ver else []) or (by_theme.get(bk, []) if bk else [])
        if not members:
            # 낱말 순서가 달라도(예: '챔피언스 2023' ↔ '2023 챔피언스') 같은 컬렉션이면 연결한다
            want = _tokens(_BUNDLE_SUFFIX.sub("", name))
            if want:
                members = next((sks for tk, sks in theme_tokens if tk == want), [])
        bundle = Bundle(b["uuid"], name, b.get("displayNameSubText"), b.get("extraDescription") or b.get("description"),
                        b.get("displayIcon") or b.get("displayIcon2") or b.get("verticalPromoImage"), members, name,
                        b.get("assetPath"), ver,
                        [u for u in (b.get("displayIcon2"), b.get("displayIcon"), b.get("verticalPromoImage")) if u])
        versions[bundle.uuid] = ver
        if members:                 # 스킨이 없는 세트(분무기·카드만 있는 묶음 등)는 뺀다
            out.append(bundle)
        else:
            dropped.append((name, "스킨 없음"))

    # 이름이 같은 세트(2.0·3.0 판 등)는 하나만 남긴다: 스킨이 가장 많은 것 → 버전 표기가 없는 원본 → 먼저 나온 것
    best: dict[str, Bundle] = {}
    for b in out:
        k = key(b.name)
        cur = best.get(k)
        if cur is None or (len(b.skins), b.version is None) > (len(cur.skins), cur.version is None):
            best[k] = b
    for b in out:
        if best[key(b.name)] is not b:
            dropped.append((b.name, "같은 이름 중복"))
    out = [b for b in out if best[key(b.name)] is b]
    out.sort(key=lambda b: sort_key(b.label or b.name))
    cat = Catalog(skins, out)
    cat.dropped = dropped
    return cat


def skin_price(tier_uuid: str | None, melee: bool, en_name: str | None = None) -> tuple[int | None, bool]:
    """(가격, 어림값인지). 등급이 없으면 상점 판매가 아니라서(배틀패스·보상) 가격 없음."""
    if not tier_uuid:
        return None, False
    if melee:
        exact = MELEE_PRICE.get(_norm_en(en_name or ""))
        if exact:
            return exact, False
        p = MELEE_TIER_PRICE.get(tier_uuid)
        return p, p is not None
    p = TIER_PRICE.get(tier_uuid)
    return p, p is not None and tier_uuid in APPROX_TIERS


def price_text(s: Skin) -> str | None:
    if not s.price:
        return None
    return f"{'약 ' if s.approx else ''}{s.price:,} VP"


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


async def _get_json(session, path: str, lang: str = LANG):
    async with session.get(f"{API}/{path}{'&' if '?' in path else '?'}language={lang}") as resp:
        resp.raise_for_status()
        return (await resp.json()).get("data") or []


async def _reward_levels(session) -> set[str]:
    """배틀패스·이벤트 패스에서 주는 스킨 레벨 uuid. 실패하면 빈 집합."""
    try:
        out: set[str] = set()
        for c in await _get_json(session, "contracts", "en-US"):
            for ch in (c.get("content") or {}).get("chapters") or []:
                rewards = [lv.get("reward") or {} for lv in ch.get("levels") or []] + list(ch.get("freeRewards") or [])
                out.update(r.get("uuid") for r in rewards if r.get("type") == "EquippableSkinLevel" and r.get("uuid"))
        return out
    except Exception as exc:
        log.warning("패스 보상 목록 못 받음: %s: %s", type(exc).__name__, exc)
        return set()


async def _melee_en(session) -> dict[str, str]:
    """근접 무기 스킨의 영어 이름 (가격표 찾기용). 실패해도 등급 어림값으로 동작."""
    try:
        w = await _get_json(session, f"weapons/{MELEE_WEAPON}", "en-US")
        return {s["uuid"]: s.get("displayName") or "" for s in (w.get("skins") or []) if s.get("uuid")}
    except Exception as exc:
        log.warning("근접 무기 영어 이름 못 받음 (가격은 등급 어림값): %s: %s", type(exc).__name__, exc)
        return {}


async def load(force: bool = False) -> Catalog:
    global _catalog
    async with _lock:
        if _catalog and not force and time.monotonic() - _catalog.loaded_at < TTL:
            return _catalog
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "ValoProBot/0.3"}) as session:
            weapons, tiers, themes, bundles, melee_en, rewards = await asyncio.gather(
                _get_json(session, "weapons"), _get_json(session, "contenttiers"),
                _get_json(session, "themes"), _get_json(session, "bundles"), _melee_en(session), _reward_levels(session))
        cat = parse_catalog(weapons, tiers, themes, bundles, melee_en, rewards)
        log.info("패스 보상 스킨 레벨 %d개 (가격 없음 처리)", len(rewards))
        log.info("근접 무기 영어 이름(어림값): %s", " | ".join(
            f"{melee_en.get(s.uuid, '?')}={short_tier(s.tier)}" for s in cat.skins if s.melee and s.approx))
        cat.loaded_at = time.monotonic()
        _catalog = cat
        log.info("스킨 목록 불러옴: 스킨 %d · 번들 %d", len(cat.skins), len(cat.bundles))
        melee = [s for s in cat.skins if s.melee and s.price]
        log.info("근접 무기 가격: 가격표 %d개 · 어림값 %d개 (어림: %s)", sum(not s.approx for s in melee),
                 sum(s.approx for s in melee), ", ".join(s.name for s in melee if s.approx))
        excl: dict[str, list[str]] = {}
        for s in cat.skins:
            if not s.melee and s.price and s.approx:
                excl.setdefault(s.theme or "?", []).append(s.name)
        log.info("익스클루시브 총기 컬렉션 %d개: %s", len(excl), " | ".join(f"{k}[{len(v)}]: {v[0]}" for k, v in excl.items()))
        log.info("목록에 있는 세트 %d개: %s", len(cat.bundles), ", ".join(f"{b.name}[{len(b.skins)}]" for b in cat.bundles))
        if cat.dropped:
            log.info("목록에서 빠진 세트 %d개: %s", len(cat.dropped), ", ".join(f"{n}({r})" for n, r in cat.dropped))
        return cat


BIG_IMAGE = int(2.5 * 1024 * 1024)   # 세트 그림은 이 크기까지만 받는다 (원본 displayIcon 은 8MB가 넘기도 해서 느리고 메모리를 많이 씀)


def set_tier(b: Bundle) -> Skin | None:
    """세트의 대표 등급을 가진 스킨 (등급 아이콘·이름·색을 여기서 읽는다). 가장 많은 등급, 같으면 더 비싼 쪽."""
    tiered = [s for s in b.skins if s.tier]
    if not tiered:
        return b.skins[0] if b.skins else None
    count: dict[str, int] = {}
    for s in tiered:
        count[s.tier] = count.get(s.tier, 0) + 1
    return max(tiered, key=lambda s: (count[s.tier], s.price or 0))


def short_tier(name: str | None) -> str:
    return re.sub(r"\s*에디션$", "", name or "")


def weapon_names(cat: Catalog) -> list[str]:
    """스킨이 있는 무기 이름 (처음 나온 순서, 근접 무기는 마지막)."""
    seen: list[str] = []
    for s in cat.skins:
        if s.weapon and s.weapon not in seen:
            seen.append(s.weapon)
    melee = {s.weapon for s in cat.skins if s.melee}
    return [w for w in seen if w not in melee] + [w for w in seen if w in melee]


def tier_names(cat: Catalog, weapon: str | None = None) -> list[str]:
    """등급 이름을 싼 것부터 (무기를 주면 그 무기에 있는 등급만)."""
    price: dict[str, int] = {}
    for s in cat.skins:
        if s.tier:
            price[s.tier] = max(price.get(s.tier, 0), s.price or 0)
    present = {s.tier for s in cat.skins if s.tier and (weapon is None or s.weapon == weapon)}
    return sorted(present, key=lambda n: (price.get(n, 0) == 0, price.get(n, 0), n))


def list_skins(cat: Catalog, weapon: str, tier: str | None = None) -> list[Skin]:
    """무기(와 등급)로 거른 스킨, 숫자 → 영어 → 가나다 순."""
    found = [s for s in cat.skins if s.weapon == weapon and (tier is None or s.tier == tier)]
    return sorted(found, key=lambda s: sort_key(s.label or s.name))


def icon_urls(b: Bundle) -> list[str]:
    """세트 그림 후보 주소: 세트 그림들 → 마지막엔 첫 스킨의 그림."""
    urls = list(b.icons) or ([b.icon] if b.icon else [])
    urls += [s.icon for s in b.skins[:1] if s.icon]
    return urls


async def fetch_icon(b: Bundle, big: bool = False):
    """후보를 차례로 시도해 처음 받아지는 그림을 돌려준다 (너무 큰 파일은 받기 전에 건너뜀)."""
    from bot.render import images

    for u in icon_urls(b):
        img = await (images.fetch_big(u, 700, BIG_IMAGE) if big else images.fetch_image(u, BIG_IMAGE))
        if img is not None:
            return img
    return None


async def warm_icons(cat: Catalog, first: int = 0) -> None:
    """세트 그림을 뒤에서 미리 받아 둔다 (목록 격자가 바로 뜨도록).

    메모리·CPU가 작은 서버라서 한 장씩, 천천히 받는다 (그림 풀기는 images._DECODE 로 한 번에 한 장).
    first: 이 번호부터 먼저 받는다 (보고 있는 쪽 다음 쪽을 먼저).
    """
    order = cat.bundles[first:] + cat.bundles[:first]
    t0 = time.monotonic()
    ok = 0
    try:
        notes = []
        for b in order:
            img = await fetch_icon(b)
            if img is not None:
                ok += 1
                if "챔피언스" in b.name:
                    box = img.getbbox() if img.mode != "RGBA" else img.getchannel("A").getbbox()
                    notes.append(f"{b.name}: {img.size} {img.mode} 보이는영역={box} 후보={[u.rsplit('/', 2)[-2][:8] + '/' + u.rsplit('/', 1)[-1] for u in icon_urls(b)]}")
            else:
                notes.append(f"{b.name}: 그림 없음 후보={icon_urls(b)}")
            await asyncio.sleep(0.2)
        if notes:
            log.info("세트 그림 진단: %s", " | ".join(notes))
    except Exception as exc:
        log.warning("세트 그림 미리 받기 실패: %s: %s", type(exc).__name__, exc)
        return
    log.info("세트 그림 미리 받기: %d/%d개 (%.0f초)", ok, len(order), time.monotonic() - t0)


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
