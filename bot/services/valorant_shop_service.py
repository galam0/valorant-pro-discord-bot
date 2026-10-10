"""발로란트 개인 상점 — 제공자 경계와 상태 처리.

현재는 **허용된 데이터 제공자가 없다.** Riot 공식 API/RSO 는 개인 상점 조회를 제공하지 않고, 비공식 방식(비밀번호·쿠키
수집, 비공개 엔드포인트)은 쓰지 않기로 했다. 그래서 기본 제공자(NoShopProvider)는 항상 '지원 안 함'을 알린다.
나중에 Riot 이 허용하는 방식이 생기면 ShopProvider 를 구현해 `provider` 에 꽂기만 하면 된다.
(이 모듈은 DB·discord 에 의존하지 않아 테스트하기 쉽다.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ShopItem:
    name: str
    image_url: str | None = None
    price: int | None = None
    discount_pct: int | None = None      # 야시장 할인율 (제공자가 주는 경우만)
    original_price: int | None = None


@dataclass
class ShopResult:
    items: list[ShopItem] = field(default_factory=list)
    note: str | None = None


class ProviderNotConfigured(RuntimeError):
    """허용된 상점 데이터 제공자가 없음."""


class AuthExpired(RuntimeError):
    """제공자가 '인증이 만료됐다'고 알려줌 → 다시 연동해야 한다."""


class ShopProvider(Protocol):
    name: str
    available: bool

    async def begin_link(self, discord_user_id: int) -> str:
        """Riot/제공자의 **공식 로그인 페이지** 주소를 돌려준다 (유저가 그 페이지에서 직접 인증).
        봇은 비밀번호·쿠키를 받지 않는다."""
        ...

    async def get_daily_store(self, discord_user_id: int) -> ShopResult: ...
    async def get_night_market(self, discord_user_id: int) -> ShopResult: ...


class NoShopProvider:
    """기본값: 명령어는 동작하지만 '지원되지 않는다'고 분명하게 알린다. 가짜 상점을 보여주지 않는다."""

    name = "none"
    available = False

    async def begin_link(self, discord_user_id: int) -> str:
        raise ProviderNotConfigured("허용된 연동 방식이 없습니다.")

    async def get_daily_store(self, discord_user_id: int) -> ShopResult:
        raise ProviderNotConfigured("허용된 상점 데이터 제공자가 없습니다.")

    async def get_night_market(self, discord_user_id: int) -> ShopResult:
        raise ProviderNotConfigured("허용된 상점 데이터 제공자가 없습니다.")


provider: ShopProvider = NoShopProvider()

UNSUPPORTED = (
    "개인 상점 조회는 **지원하지 않아요.**\n"
    "Riot 공식 API에는 개인 상점 조회가 없고, 계정 비밀번호나 로그인 정보를 받는 비공식 방식은 "
    "이 봇에서 쓰지 않아요. 대신 `/스킨`, `/번들`로 스킨 정보를 볼 수 있어요."
)


def link_state(row_status: str | None, prov: ShopProvider) -> str:
    """'unsupported' | 'not_linked' | 'expired' | 'linked'"""
    if not prov.available:
        return "unsupported"
    if row_status == "linked":
        return "linked"
    if row_status == "expired":
        return "expired"
    return "not_linked"


STATE_TEXT = {
    "unsupported": UNSUPPORTED,
    "not_linked": "연동된 계정이 없어요. 먼저 계정을 연동해주세요.",
    "expired": "인증이 만료됐어요. 다시 연동해주세요.",
}
