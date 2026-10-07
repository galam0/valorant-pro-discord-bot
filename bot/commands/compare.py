"""/비교 — 두 팀 비교 (DB에 저장된 정보만 사용)."""

from __future__ import annotations

import logging
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from bot.autocomplete import team_autocomplete
from bot.database.database import db
from bot.embeds.common import COLOR_MAIN, error_embed
from bot.render.cards import build_compare_card
from bot.services import compare_service

log = logging.getLogger("valobot.cmd.compare")


def _fallback_embed(r: compare_service.CompareResult) -> discord.Embed:
    a_w = b_w = 0
    for m in r.h2h:
        mine, other = (m.team1_score, m.team2_score) if m.team1_id == r.a.team.id else (m.team2_score, m.team1_score)
        if mine is not None and other is not None:
            a_w += mine > other
            b_w += mine < other
    embed = discord.Embed(title=f"⚔️ {r.a.team.name} vs {r.b.team.name}", color=COLOR_MAIN)
    for d in (r.a, r.b):
        roster = ", ".join(m.name for m in d.members if m.role in ("player", "substitute"))[:1000] or "-"
        embed.add_field(name=d.team.name, value=roster, inline=False)
    embed.add_field(name="맞대결 (저장된 경기)", value=f"{r.a.team.name} {a_w}승 · {r.b.team.name} {b_w}승", inline=False)
    return embed


class CompareCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="비교", description="두 팀의 최근 성적·로스터·맞대결을 비교합니다.")
    @app_commands.describe(팀1="첫 번째 팀 (예: T1, 젠지)", 팀2="두 번째 팀 (예: DRX, 농심)")
    @app_commands.autocomplete(팀1=team_autocomplete, 팀2=team_autocomplete)
    async def compare(self, interaction: discord.Interaction, 팀1: str, 팀2: str) -> None:
        if not db.configured:
            await interaction.response.send_message(embed=error_embed("현재 데이터를 불러올 수 없습니다."), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            result = await compare_service.compare(팀1, 팀2)
        except compare_service.CompareError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return
        except Exception:
            log.exception("팀 비교 실패: %s vs %s", 팀1, 팀2)
            await interaction.followup.send(embed=error_embed("현재 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요."))
            return

        png = await build_compare_card(result)
        if png is not None:
            await interaction.followup.send(file=discord.File(BytesIO(png), filename="compare.png"))
        else:
            await interaction.followup.send(embed=_fallback_embed(result))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompareCommands(bot))
