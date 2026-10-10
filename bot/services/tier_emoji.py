"""등급 아이콘(실제 게임 등급 그림)을 봇 전용 이모지로 올려 두고, 선택 메뉴 같은 곳에서 쓴다.

- 디스코드 '애플리케이션 이모지'를 쓴다 (서버 이모지 칸을 쓰지 않고, 봇이 어느 서버에서든 쓸 수 있음).
- 이미 올라가 있으면 다시 올리지 않는다. 실패하면 이모지 없이 동작한다 (카드 이미지에는 아이콘이 직접 그려짐).
"""

from __future__ import annotations

import logging
import re
from io import BytesIO

log = logging.getLogger("valobot.tier_emoji")

_by_url: dict[str, object] = {}


def emoji_name(icon_url: str) -> str:
    """등급 아이콘 주소의 uuid 앞 8글자로 이름을 만든다 (이모지 이름: 영문·숫자·밑줄 2~32자)."""
    m = re.search(r"contenttiers/([0-9a-f]{8})", icon_url or "")
    return f"tier_{m.group(1)}" if m else "tier_" + re.sub(r"[^0-9a-z]", "", (icon_url or "x").lower())[-8:]


def emoji_for(icon_url: str | None):
    return _by_url.get(icon_url or "")


def _to_png(img, size: int = 96) -> bytes:
    img = img.copy()
    img.thumbnail((size, size))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def ensure(bot) -> None:
    """등급 아이콘을 이모지로 준비한다 (봇이 켜진 뒤 한 번, 뒤에서)."""
    try:
        from bot.render import images
        from bot.services import skin_service

        cat = await skin_service.load()
        urls = sorted({s.tier_icon for s in cat.skins if s.tier_icon})
        existing = {e.name: e for e in await bot.fetch_application_emojis()}
        for url in urls:
            name = emoji_name(url)
            emoji = existing.get(name)
            if emoji is None:
                pic = await images.fetch_image(url)
                if pic is None:
                    continue
                emoji = await bot.create_application_emoji(name=name, image=_to_png(pic))
            _by_url[url] = emoji
        log.info("등급 이모지 준비: %d개", len(_by_url))
    except Exception as exc:
        log.warning("등급 이모지 준비 실패 (이모지 없이 동작): %s: %s", type(exc).__name__, exc)
