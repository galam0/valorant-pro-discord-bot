"""예측 정산 결과를 서버의 알림 채널에 올린다 (/채널설정 알림)."""

from __future__ import annotations

import logging

import discord

from bot.services import guild_settings

log = logging.getLogger("valobot.service.announce")


def make_announcer(bot: discord.Client):
    async def announce(guild_id: int, embed: discord.Embed, content: str | None = None,
                       mention_users: list[int] | None = None) -> None:
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
            allowed = (discord.AllowedMentions(users=[discord.Object(id=u) for u in mention_users], roles=False, everyone=False)
                       if mention_users else discord.AllowedMentions.none())
            await channel.send(content=content, embed=embed, allowed_mentions=allowed)
        except discord.HTTPException as exc:
            log.info("알림 채널 전송 실패 (guild %s): %s", guild_id, exc)

    return announce


def make_broadcaster(bot: discord.Client):
    """봇이 들어가 있는 모든 서버의 알림 채널에 같은 알림을 올린다."""
    announce = make_announcer(bot)

    async def broadcast(embed: discord.Embed, fans_for=None) -> None:
        """fans_for(guild_id) → 그 서버에서 멘션할 유저 ID들 (없으면 멘션 없이 올린다)."""
        for guild in list(bot.guilds):
            try:
                fans = await fans_for(guild.id) if fans_for else []
                content = ("📣 응원 팀 경기예요! " + " ".join(f"<@{u}>" for u in fans)) if fans else None
                await announce(guild.id, embed, content, fans)
            except Exception as exc:
                log.info("알림 실패 (guild %s): %s", guild.id, exc)

    return broadcast
