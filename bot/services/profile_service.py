"""/프로필·/상점·/꾸미기 의 DB 처리."""

from __future__ import annotations

from bot.database import economy
from bot.database.database import db
from bot.services import shop_catalog
from bot.services.economy_service import rank_info
from bot.services.shop_catalog import BY_ID, DEFAULTS, FREE_IDS


class ShopError(Exception):
    """사용자에게 그대로 보여줄 메시지."""


async def card_data(guild_id: int, user_id: int, name: str) -> dict:
    async with db.session() as s:
        bal = await economy.get_balance(s, guild_id, user_id)
        await s.commit()
        prof = await economy.get_profile(s, guild_id, user_id)
        won, total = await economy.prediction_record(s, guild_id, user_id)
    rank, _ = await rank_info(guild_id, user_id)
    title_id = prof.title if prof else DEFAULTS["title"]
    title = BY_ID[title_id].name if title_id in BY_ID and title_id != DEFAULTS["title"] else ""
    return {
        "name": name, "title": title,
        "theme": prof.theme if prof else DEFAULTS["theme"], "frame": prof.frame if prof else DEFAULTS["frame"],
        "vp": bal, "rank": rank, "pred_win": won, "pred_total": total,
        "fav_team": prof.fav_team if prof else None, "fav_agent": prof.fav_agent if prof else None,
    }


async def owned(guild_id: int, user_id: int) -> set[str]:
    async with db.session() as s:
        return await economy.owned_items(s, guild_id, user_id)


async def balance_and_owned(guild_id: int, user_id: int) -> tuple[int, set[str]]:
    async with db.session() as s:
        bal = await economy.get_balance(s, guild_id, user_id)
        await s.commit()
        have = await economy.owned_items(s, guild_id, user_id)
    return bal, have


async def buy(guild_id: int, user_id: int, item_id: str) -> int:
    item = BY_ID.get(item_id)
    if item is None or item.price <= 0:
        raise ShopError("살 수 없는 상품이에요.")
    try:
        async with db.session() as s:
            bal = await economy.buy_item(s, guild_id, user_id, item_id, item.price)
            await s.commit()
    except economy.AlreadyOwned:
        raise ShopError("이미 가지고 있어요.") from None
    except economy.InsufficientFunds:
        raise ShopError(f"VP가 부족해요. ({item.price:,} VP 필요)") from None
    return bal


async def equip(guild_id: int, user_id: int, item_id: str) -> None:
    item = BY_ID.get(item_id)
    if item is None:
        raise ShopError("알 수 없는 상품이에요.")
    async with db.session() as s:
        have = await economy.owned_items(s, guild_id, user_id)
        if not shop_catalog.owned_or_free(item_id, have):
            raise ShopError("아직 갖고 있지 않은 상품이에요. `/상점`에서 먼저 구매해주세요.")
        await economy.upsert_profile(s, guild_id, user_id, **{item.kind: item_id})
        await s.commit()


async def set_favs(guild_id: int, user_id: int, team: str | None, agent: str | None) -> None:
    fields = {}
    if team:
        fields["fav_team"] = team[:120]
    if agent:
        if agent not in shop_catalog.AGENTS:
            raise ShopError("요원 이름을 자동완성에서 골라주세요.")
        fields["fav_agent"] = agent
    if not fields:
        raise ShopError("바꿀 항목(응원팀 또는 최애요원)을 입력해주세요.")
    async with db.session() as s:
        await economy.upsert_profile(s, guild_id, user_id, **fields)
        await s.commit()


async def current_equipped(guild_id: int, user_id: int) -> dict[str, str]:
    async with db.session() as s:
        prof = await economy.get_profile(s, guild_id, user_id)
    if prof is None:
        return dict(DEFAULTS)
    return {"theme": prof.theme, "frame": prof.frame, "title": prof.title}
