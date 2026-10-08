"""서버별 설정(/채널설정) 조회. 명령어마다 DB를 부르지 않도록 60초 캐시한다."""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands

from bot.database.database import db
from bot.utils.config import settings

log = logging.getLogger("valobot.service.guild_settings")

TTL = 60.0
_cache: dict[int, tuple[float, int | None, int | None]] = {}   # guild -> (조회 시각, 게임 채널, 알림 채널)


class ChannelRestricted(app_commands.CheckFailure):
    """게임 채널이 따로 정해진 서버에서 다른 채널로 명령어를 썼을 때."""

    def __init__(self, channel_id: int) -> None:
        super().__init__(f"게임 채널 {channel_id}")
        self.channel_id = channel_id


async def get(guild_id: int) -> tuple[int | None, int | None]:
    """(게임 채널 ID, 알림 채널 ID). DB 오류가 나도 명령어를 막지 않도록 (None, None)을 돌려준다."""
    hit = _cache.get(guild_id)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1], hit[2]
    if not db.configured:
        return None, None
    from bot.database import economy

    try:
        async with db.session() as s:
            row = await economy.get_guild_setting(s, guild_id)
    except Exception as exc:
        log.warning("서버 설정 조회 실패: %s: %s", type(exc).__name__, exc)
        return (hit[1], hit[2]) if hit else (None, None)
    game, notice = (row.game_channel_id, row.notice_channel_id) if row else (None, None)
    _cache[guild_id] = (time.monotonic(), game, notice)
    return game, notice


async def set_channel(guild_id: int, field: str, channel_id: int | None) -> None:
    from bot.database import economy

    async with db.session() as s:
        await economy.set_guild_channel(s, guild_id, field, channel_id)
        await s.commit()
    _cache.pop(guild_id, None)


def bypasses(interaction: discord.Interaction) -> bool:
    """봇 관리자·서버 관리자는 게임 채널 제한을 받지 않는다."""
    if interaction.user.id in settings.admin_user_ids:
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.administrator)


async def check_game_channel(interaction: discord.Interaction) -> bool:
    """게임 채널이 정해져 있고 다른 채널에서 썼다면 ChannelRestricted 를 낸다."""
    if interaction.guild_id is None or bypasses(interaction):
        return True
    game, _ = await get(interaction.guild_id)
    if game is not None and interaction.channel_id != game:
        raise ChannelRestricted(game)
    return True
