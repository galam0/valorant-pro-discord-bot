"""블라인드/스킨 퀴즈 자료: valorant-api.com(커뮤니티 공개 API)에서 요원·무기·스킨 이름(한국어)과 그림 주소를 받는다.

12시간 메모리 캐시. 받지 못하면 호출한 쪽이 글 퀴즈로 대신한다.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass

from bot.scrapers.http import http_client

log = logging.getLogger("valobot.service.quiz_assets")

AGENTS_URL = "https://valorant-api.com/v1/agents?isPlayableCharacter=true&language=ko-KR"
WEAPONS_URL = "https://valorant-api.com/v1/weapons?language=ko-KR"
TTL = 12 * 3600
MELEE_KEY = "근접"
SKIP_SKIN_WORDS = ("스탠다드", "랜덤", "Standard", "Random")

KINDS = ("agent", "weapon", "skin")
KIND_KO = {"agent": "요원 블라인드", "weapon": "무기 블라인드", "skin": "스킨 이름 맞추기"}


@dataclass
class VisualQuiz:
    kind: str
    question: str
    art_url: str
    options: list[str]
    answer: int
    answer_label: str       # 정답 공개 때 그림 아래에 쓸 이름


_cache: dict[str, tuple[float, object]] = {}


async def _json(url: str) -> dict:
    hit = _cache.get(url)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]  # type: ignore[return-value]
    data = json.loads(await http_client.get_text(url))
    _cache[url] = (time.monotonic(), data)
    return data


def _opts(answer: str, pool: list[str], rng: random.Random) -> tuple[list[str], int]:
    wrong = [p for p in dict.fromkeys(pool) if p != answer]
    options = [answer] + rng.sample(wrong, 3)
    rng.shuffle(options)
    return options, options.index(answer)


async def make_visual(kind: str, rng: random.Random | None = None) -> VisualQuiz:
    """kind: agent / weapon / skin. 실패하면 예외 (호출한 쪽에서 글 퀴즈로 대체)."""
    r = rng or random
    if kind == "agent":
        agents = [a for a in (await _json(AGENTS_URL))["data"] if a.get("fullPortrait") or a.get("bustPortrait")]
        a = r.choice(agents)
        options, ans = _opts(a["displayName"], [x["displayName"] for x in agents], r)
        return VisualQuiz("agent", "그림자의 주인공은 어느 요원일까요?", a.get("fullPortrait") or a["bustPortrait"],
                          options, ans, a["displayName"])

    weapons = [w for w in (await _json(WEAPONS_URL))["data"] if w.get("skins")]
    if kind == "weapon":
        guns = [w for w in weapons if MELEE_KEY not in w["displayName"]]
        w = r.choice(guns)
        skins = [s for s in w["skins"] if s.get("displayIcon") and not any(k in s["displayName"] for k in SKIP_SKIN_WORDS)]
        icon = r.choice(skins)["displayIcon"] if skins else w["displayIcon"]
        options, ans = _opts(w["displayName"], [g["displayName"] for g in guns], r)
        return VisualQuiz("weapon", "그림자의 무기는 무엇일까요?", icon, options, ans, w["displayName"])

    guns = [w for w in weapons if MELEE_KEY not in w["displayName"]]
    w = r.choice(guns)
    skins = [s for s in w["skins"] if s.get("displayIcon") and not any(k in s["displayName"] for k in SKIP_SKIN_WORDS)]
    if len(skins) < 4:
        raise RuntimeError("스킨이 부족합니다")
    s = r.choice(skins)
    options, ans = _opts(s["displayName"], [x["displayName"] for x in skins], r)
    return VisualQuiz("skin", f"이 {w['displayName']} 스킨의 이름은?", s["displayIcon"], options, ans, s["displayName"])
