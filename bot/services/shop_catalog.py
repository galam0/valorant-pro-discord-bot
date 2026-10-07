"""VP 상점 상품 목록 (순수 데이터). 가격을 바꾸려면 여기만 고치면 된다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: str
    kind: str       # theme / frame / title
    name: str
    price: int
    desc: str = ""


KIND_KO = {"theme": "배경", "frame": "테두리", "title": "칭호"}
DEFAULTS = {"theme": "theme_default", "frame": "frame_none", "title": "title_none"}

ITEMS: list[Item] = [
    Item("theme_default", "theme", "기본", 0, "네이비 + 레드"),
    Item("theme_sunset", "theme", "노을", 800, "보라·핑크 노을"),
    Item("theme_ocean", "theme", "바다", 800, "깊은 바다 파랑"),
    Item("theme_forest", "theme", "숲", 800, "차분한 초록"),
    Item("theme_gold", "theme", "골드", 2500, "카지노 골드"),
    Item("frame_none", "frame", "없음", 0, ""),
    Item("frame_silver", "frame", "실버", 1000, "은색 링"),
    Item("frame_neon", "frame", "네온", 2000, "시안 네온 링"),
    Item("frame_gold", "frame", "골드", 2500, "금빛 링"),
    Item("frame_rainbow", "frame", "무지개", 3500, "무지개 링"),
    Item("title_none", "title", "칭호 없음", 0, ""),
    Item("title_rookie", "title", "뉴비", 0, "누구나"),
    Item("title_fan", "title", "VALORANT 덕후", 800, ""),
    Item("title_slot", "title", "슬롯 중독자", 1000, ""),
    Item("title_blind", "title", "블라인드 마스터", 1500, ""),
    Item("title_oracle", "title", "예측 장인", 1500, ""),
    Item("title_lucky", "title", "행운아", 2000, ""),
    Item("title_rich", "title", "큰손", 5000, ""),
]
BY_ID = {i.id: i for i in ITEMS}
FREE_IDS = {i.id for i in ITEMS if i.price == 0}

AGENTS = ["게코", "페이드", "브리치", "데드록", "테호", "레이즈", "체임버", "케이/오", "스카이", "사이퍼", "소바", "믹스",
          "킬조이", "하버", "바이스", "바이퍼", "피닉스", "비토", "아스트라", "브림스톤", "아이소", "클로브", "네온", "요루",
          "웨이레이", "세이지", "레이나", "오멘", "제트"]


def by_kind(kind: str) -> list[Item]:
    return [i for i in ITEMS if i.kind == kind]


def owned_or_free(item_id: str, owned: set[str]) -> bool:
    return item_id in BY_ID and (item_id in FREE_IDS or item_id in owned)
