"""/랭킹 — VLR.gg 팀 랭킹 (이미지 카드)."""

from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import COLOR_MAIN, error_embed
from bot.render.cards import build_ranking_card
from bot.scrapers.http import ScrapeError
from bot.scrapers.vlr import ParseError
from bot.services import ranking_service

log = logging.getLogger("valobot.cmd.ranking")

TOP_N = 15
DEFAULT_REGION = "korea"


def _streak(n: int | None) -> str:
    if n and n >= 2:
        return f" · {n}연승"
    if n and n <= -2:
        return f" · {-n}연패"
    return ""


class RankingCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="랭킹", description="VLR.gg 팀 랭킹을 보여줍니다.")
    @app_commands.describe(지역="랭킹 지역 (기본: 한국)", 범위="1군 팀만 볼지, 아카데미·챌린저스 팀까지 모두 볼지")
    @app_commands.choices(
        지역=[app_commands.Choice(name=ko, value=code) for code, ko in ranking_service.REGIONS],
        범위=[app_commands.Choice(name="1군 팀만", value="first"), app_commands.Choice(name="전체", value="all")],
    )
    async def ranking(
        self,
        interaction: discord.Interaction,
        지역: app_commands.Choice[str] | None = None,
        범위: app_commands.Choice[str] | None = None,
    ) -> None:
        region = 지역.value if 지역 else DEFAULT_REGION
        first_only = (범위.value if 범위 else "first") == "first"
        await interaction.response.defer(thinking=True)
        try:
            result = await ranking_service.get_ranking(region)
        except (ScrapeError, ParseError):
            log.warning("랭킹 조회 실패: %s", region, exc_info=True)
            await interaction.followup.send(embed=error_embed("랭킹을 가져오지 못했습니다. 잠시 후 다시 시도해주세요."))
            return

        if first_only:
            picked = [e for e in result.entries if ranking_service.is_first_team(e.name)]
            ranked = [(i, e) for i, e in enumerate(picked[:TOP_N], 1)]
        else:
            ranked = [(e.rank, e) for e in result.entries[:TOP_N]]
        if not ranked:
            await interaction.followup.send(embed=error_embed("표시할 팀이 없습니다. '전체' 범위로 다시 확인해보세요."))
            return

        region_ko = ranking_service.REGION_NAME[region]
        title = f"{region_ko} 팀 랭킹"
        scope = "1군 팀만 · 순위는 1군 기준" if first_only else "전체 · 순위는 VLR 기준"
        subtitle = f"VLR.gg · {scope} · 상위 {len(ranked)}팀"
        footer = "출처: VLR.gg" + (" · 최신 정보를 못 가져와 이전 결과입니다" if result.stale else "")

        png = await build_ranking_card(title, subtitle, ranked, footer)
        if png is not None:
            await interaction.followup.send(file=discord.File(BytesIO(png), filename=f"ranking_{region}.png"))
            return

        # 이미지 생성 실패 시 텍스트로 대체
        lines = []
        for rank, e in ranked:
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"`{rank:>2}`")
            pts = f"{e.rating}점" if e.rating is not None else "-"
            lines.append(f"{medal} **{e.name}** · {pts}{_streak(e.streak)}")
        embed = discord.Embed(title=f"🏆 {title}", description="\n".join(lines), color=COLOR_MAIN,
                              url=f"https://www.vlr.gg/rankings/{region}")
        embed.set_footer(text=f"{subtitle} · {footer}")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RankingCommands(bot))
