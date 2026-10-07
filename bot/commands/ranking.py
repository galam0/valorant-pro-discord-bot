"""/랭킹 — VLR.gg 팀 랭킹."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import COLOR_MAIN, error_embed
from bot.scrapers.http import ScrapeError
from bot.scrapers.vlr import ParseError
from bot.services import ranking_service

log = logging.getLogger("valobot.cmd.ranking")

TOP_N = 15


def _streak(n: int | None) -> str:
    if not n:
        return ""
    return f" · {n}연승" if n > 0 and n >= 2 else f" · {-n}연패" if n <= -2 else ""


class RankingCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="랭킹", description="VLR.gg 팀 랭킹을 보여줍니다.")
    @app_commands.describe(지역="랭킹 지역 (기본: 세계)")
    @app_commands.choices(지역=[app_commands.Choice(name=ko, value=code) for code, ko in ranking_service.REGIONS])
    async def ranking(self, interaction: discord.Interaction, 지역: app_commands.Choice[str] | None = None) -> None:
        region = 지역.value if 지역 else "world"
        await interaction.response.defer(thinking=True)
        try:
            result = await ranking_service.get_ranking(region)
        except (ScrapeError, ParseError):
            log.warning("랭킹 조회 실패: %s", region, exc_info=True)
            await interaction.followup.send(embed=error_embed("랭킹을 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
            return

        lines = []
        for e in result.entries[:TOP_N]:
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(e.rank, f"`{e.rank:>2}`")
            pts = f"{e.rating}점" if e.rating is not None else "-"
            country = f" · {e.country}" if e.country and region == "world" else ""
            lines.append(f"{medal} **{e.name}** · {pts}{_streak(e.streak)}{country}")
        embed = discord.Embed(
            title=f"🏆 {ranking_service.REGION_NAME[region]} 팀 랭킹",
            description="\n".join(lines),
            color=COLOR_MAIN,
            url=f"https://www.vlr.gg/rankings{'' if region == 'world' else '/' + region}",
        )
        footer = f"상위 {min(TOP_N, len(result.entries))}팀 · 출처: VLR.gg"
        if result.stale:
            footer += " · ⚠️ 최신 정보를 못 가져와 이전 결과입니다"
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RankingCommands(bot))
