"""예측 정산 결과를 서버의 알림 채널에 올린다 (/채널설정 알림)."""

from __future__ import annotations

import logging

import discord

from bot.services import guild_settings

log = logging.getLogger("valobot.service.announce")


def make_announcer(bot: discord.Client):
    async def announce(guild_id: int, embed: discord.Embed) -> None:
        _, notice = await guild_settings.get(guild_id)
        if notice is None:
            return
        channel = bot.get_channel(notice)
        if channel is None:
            try:
                channel = await bot.fetch_channel(notice)
            except discord.HTTPException:
                return
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.info("알림 채널 전송 실패 (guild %s): %s", guild_id, exc)

    return announce
