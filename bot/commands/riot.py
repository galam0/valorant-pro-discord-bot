"""/유저전적 — 일반 유저의 랭크·최근 경쟁전 전적 (계정 로그인 없이 '이름#태그'만 조회)."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.embeds.common import COLOR_MAIN, error_embed
from bot.render import images, riot_card
from bot.render.base import render_enabled
from bot.services import riot_stats as rs
from bot.services.riot_stats import RiotError, tier_ko

log = logging.getLogger("valobot.cmd.riot")
_RENDER_SEM = asyncio.Semaphore(2)

REGION_CHOICES = [
    app_commands.Choice(name="한국", value="kr"),
    app_commands.Choice(name="아시아태평양", value="ap"),
    app_commands.Choice(name="북미", value="na"),
    app_commands.Choice(name="유럽", value="eu"),
]


def _text_embed(s: rs.UserStats) -> discord.Embed:
    """그림을 못 그릴 때(폰트 없음 등)의 글자 버전."""
    rank = tier_ko(s.tier_id) + (f" · {s.rr}RR" if s.rr is not None and (s.tier_id or 0) >= 3 else "")
    e = discord.Embed(title=f"{s.name} #{s.tag}", description=f"**{rank}**", color=COLOR_MAIN)
    for m in s.matches:
        res = "승" if m.won else "패" if m.won is False else "-"
        e.add_field(name=f"{res} {m.map_name} · {m.agent}",
                    value=f"{m.kills}/{m.deaths}/{m.assists} · HS {m.hs_pct:.0f}% · ADR {m.adr:.0f}", inline=False)
    e.set_footer(text="데이터: HenrikDev 비공식 API")
    return e


class RiotCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="유저전적", description="유저의 현재 랭크와 최근 경쟁전 5경기를 보여줍니다.")
    @app_commands.describe(라이엇id="이름#태그 (예: Hide on bush#KR1)", 지역="계정 지역 (기본: 한국)")
    @app_commands.choices(지역=REGION_CHOICES)
    async def user_record(self, interaction: discord.Interaction, 라이엇id: str,
                          지역: app_commands.Choice[str] | None = None) -> None:
        try:
            name, tag = rs.parse_riot_id(라이엇id)
        except RiotError as exc:
            await interaction.response.send_message(embed=error_embed(str(exc)), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            stats = await rs.fetch_user(name, tag, 지역.value if 지역 else "kr")
        except RiotError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return
        except Exception:
            log.exception("유저 전적 조회 실패")
            await interaction.followup.send(embed=error_embed("유저 전적을 불러오지 못했어요. 잠시 후 다시 시도해주세요."))
            return

        if not render_enabled():
            await interaction.followup.send(embed=_text_embed(stats))
            return
        try:
            async with _RENDER_SEM:
                tier_img = await images.fetch_image(await rs.tier_icon_url(stats.tier_id))
                ids = list(dict.fromkeys(m.agent_id for m in stats.matches if m.agent_id))
                agents = await images.fetch_many({i: rs.agent_icon_url(i) for i in ids})
                data = await asyncio.to_thread(riot_card.render_user_card, stats, tier_img, agents)
        except Exception:
            log.exception("유저 전적 카드 생성 실패")
            await interaction.followup.send(embed=_text_embed(stats))
            return
        await interaction.followup.send(file=discord.File(BytesIO(data), filename="user.png"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RiotCommands(bot))
