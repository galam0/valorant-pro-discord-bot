"""팀 로고 → 봇 전용(애플리케이션) 이모지.

애플리케이션 이모지는 서버 이모지 칸을 쓰지 않고(봇당 최대 2000개), 봇이 있는 모든 서버에서 쓸 수 있다.
이름은 `team_{팀이름}` 형식 (예: team_gen_g). discord.py 2.5 이상 필요.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field

from PIL import Image

from bot.database.database import db
from bot.render import images

log = logging.getLogger("valobot.emoji")

PREFIX = "team_"
SIZE = 128
CREATE_DELAY = 1.2   # 이모지 생성은 속도 제한이 있어 천천히


def emoji_name(team_name: str) -> str:
    """Discord 이모지 이름 규칙: 영문·숫자·밑줄 2~32자."""
    slug = re.sub(r"[^0-9a-z]+", "_", team_name.lower()).strip("_")
    return (PREFIX + (slug or "x"))[:32].rstrip("_")


def prepare_png(logo: Image.Image) -> bytes:
    """로고를 128×128 투명 PNG로 (비율 유지, 가운데 정렬). 어두운 색 그대로 둔다 (밝은 테마에서도 보이게)."""
    lg = logo.convert("RGBA")
    lg.thumbnail((SIZE, SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(lg, ((SIZE - lg.width) // 2, (SIZE - lg.height) // 2), lg)
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


@dataclass
class EmojiResult:
    created: list[tuple[str, str]] = field(default_factory=list)   # (이름, 이모지 문자열)
    existed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)               # 로고 없는 팀
    failed: list[tuple[str, str]] = field(default_factory=list)    # (팀, 이유)


async def _team_logos() -> list[tuple[str, str | None]]:
    from sqlalchemy import select

    from bot.database.models import Team

    async with db.session() as s:
        rows = (await s.execute(select(Team.name, Team.logo_url).order_by(Team.name))).all()
    return [(n, u) for n, u in rows]


async def create_team_emojis(bot, *, overwrite: bool = False) -> EmojiResult:
    """DB의 모든 팀 로고로 이모지를 만든다. 이미 있는 이름은 건너뜀(overwrite면 지우고 다시 만듦)."""
    if not hasattr(bot, "create_application_emoji"):
        raise RuntimeError("discord.py 2.5 이상이 필요합니다 (requirements.txt 확인 후 재배포).")
    result = EmojiResult()
    current = {e.name: e for e in await bot.fetch_application_emojis()}
    seen: set[str] = set()
    for name, url in await _team_logos():
        ename = emoji_name(name)
        if ename in seen:      # 이름이 겹치는 팀은 첫 팀만
            continue
        seen.add(ename)
        if not url:
            result.skipped.append(name)
            continue
        if ename in current and not overwrite:
            result.existed.append((ename, str(current[ename])))
            continue
        try:
            logo = await images.fetch_image(url)
            if logo is None:
                result.failed.append((name, "로고를 내려받지 못함"))
                continue
            png = await asyncio.to_thread(prepare_png, logo)
            if ename in current:
                await current[ename].delete()
            emoji = await bot.create_application_emoji(name=ename, image=png)
            result.created.append((ename, str(emoji)))
            await asyncio.sleep(CREATE_DELAY)
        except Exception as exc:  # 한 팀 실패가 전체를 막지 않게
            log.warning("이모지 생성 실패: %s (%s)", name, exc)
            result.failed.append((name, str(exc)[:80]))
    log.info("팀 이모지: 생성 %d, 기존 %d, 로고없음 %d, 실패 %d",
             len(result.created), len(result.existed), len(result.skipped), len(result.failed))
    return result
